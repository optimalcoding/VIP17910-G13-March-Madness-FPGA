module uart_ctrl (input logic clk, reset, rx_valid, framing_error, tx_busy, sim_busy, sim_done, input logic [7:0] rx_data, input logic [31:0] win_count, total_simulations, output logic tx_start, sim_start, load_en, output logic [7:0] tx_data, output logic [5:0] load_addr, load_team_id, read_addr, output logic [31:0] num_simulations);
    localparam logic [7:0] CMD_LOAD = 8'h01, CMD_SET = 8'h02, CMD_START = 8'h03, CMD_COUNTS = 8'h04, CMD_STATUS = 8'h05, ACK = 8'h06, NAK = 8'h15;
    typedef enum logic [1:0] {WAIT_CMD, LOAD_BRACKET, SET_COUNT, SEND_REPLY} state_t;
    typedef enum logic [1:0] {SINGLE, STATUS, COUNTS} reply_t;
    state_t state;
    reply_t reply;
    logic [5:0] payload_index;
    logic [8:0] response_index, response_last;
    logic [7:0] count_offset, response_code, status_flags;
    logic [31:0] count_buffer, status_total;
    logic [63:0] seen;
    logic packet_bad, load_allowed, bracket_loaded, results_valid, invalid_team;

    assign invalid_team = (rx_data[7:6] != 0) || seen[rx_data[5:0]];
    assign tx_start = (state == SEND_REPLY) && !tx_busy && !reset;
    assign count_offset = 8'(response_index - 9'd1);
    assign read_addr = (reply == COUNTS && response_index != 0) ? count_offset[7:2] : 6'd0;

    // ACK/NAK first, followed by little-endian payload if applicable.
    always_comb begin
        tx_data = response_code;
        response_last = 0;
        case (reply)
            STATUS: begin
                response_last = 9'd5;
                case (response_index)
                    9'd1: tx_data = status_flags;
                    9'd2: tx_data = status_total[7:0];
                    9'd3: tx_data = status_total[15:8];
                    9'd4: tx_data = status_total[23:16];
                    9'd5: tx_data = status_total[31:24];
                    default: tx_data = response_code;
                endcase
            end
            COUNTS: begin
                response_last = 9'd256;
                if (response_index != 0) begin
                    case (count_offset[1:0])
                        2'd0: tx_data = win_count[7:0];
                        2'd1: tx_data = win_count[15:8];
                        2'd2: tx_data = win_count[23:16];
                        2'd3: tx_data = win_count[31:24];
                    endcase
                end
            end
            default: tx_data = response_code;
        endcase
    end

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= WAIT_CMD;
            reply <= SINGLE;
            response_index <= 0;
            response_code <= ACK;
            payload_index <= 0;
            count_buffer <= 0;
            status_flags <= 0;
            status_total <= 0;
            seen <= 0;
            packet_bad <= 0;
            load_allowed <= 0;
            bracket_loaded <= 0;
            results_valid <= 0;
            num_simulations <= 0;
            sim_start <= 0;
            load_en <= 0;
            load_addr <= 0;
            load_team_id <= 0;
        end
        else begin
            sim_start <= 0;
            load_en <= 0;
            if (sim_done)
                results_valid <= 1;
            if (framing_error && state != SEND_REPLY) begin
                reply <= SINGLE;
                response_code <= NAK;
                response_index <= 0;
                state <= SEND_REPLY;
            end
            else begin
                case (state)
                    WAIT_CMD: begin
                        if (rx_valid) begin
                            response_index <= 0;
                            reply <= SINGLE;
                            response_code <= ACK;
                            case (rx_data)
                                CMD_LOAD: begin
                                    payload_index <= 0;
                                    seen <= 0;
                                    load_allowed <= !sim_busy;
                                    packet_bad <= sim_busy;
                                    if (!sim_busy) begin
                                        bracket_loaded <= 0;
                                        results_valid <= 0;
                                    end
                                    state <= LOAD_BRACKET;
                                end
                                CMD_SET: begin
                                    payload_index <= 0;
                                    count_buffer <= 0;
                                    packet_bad <= sim_busy;
                                    state <= SET_COUNT;
                                end
                                CMD_START: begin
                                    if (sim_busy || !bracket_loaded)
                                        response_code <= NAK;
                                    else begin
                                        sim_start <= 1;
                                        results_valid <= 0;
                                    end
                                    state <= SEND_REPLY;
                                end
                                CMD_COUNTS: begin
                                    if (sim_busy || !(results_valid || sim_done))
                                        response_code <= NAK;
                                    else
                                        reply <= COUNTS;
                                    state <= SEND_REPLY;
                                end
                                CMD_STATUS: begin
                                    status_flags <= {5'b0, bracket_loaded, (results_valid || sim_done), sim_busy};
                                    status_total <= total_simulations;
                                    reply <= STATUS;
                                    state <= SEND_REPLY;
                                end
                                default: begin
                                    response_code <= NAK;
                                    state <= SEND_REPLY;
                                end
                            endcase
                        end
                    end
                    LOAD_BRACKET: begin
                        if (rx_valid) begin
                            if (invalid_team)
                                packet_bad <= 1;
                            else begin
                                seen[rx_data[5:0]] <= 1;
                                if (load_allowed) begin
                                    load_en <= 1;
                                    load_addr <= payload_index;
                                    load_team_id <= rx_data[5:0];
                                end
                            end
                            if (payload_index == 6'd63) begin
                                if (packet_bad || invalid_team)
                                    response_code <= NAK;
                                else
                                    bracket_loaded <= 1;
                                state <= SEND_REPLY;
                            end
                            else
                                payload_index <= payload_index + 1'b1;
                        end
                    end
                    SET_COUNT: begin
                        if (rx_valid) begin
                            case (payload_index[1:0])
                                2'd0: count_buffer[7:0] <= rx_data;
                                2'd1: count_buffer[15:8] <= rx_data;
                                2'd2: count_buffer[23:16] <= rx_data;
                                2'd3: begin
                                    if (packet_bad)
                                        response_code <= NAK;
                                    else
                                        num_simulations <= {rx_data, count_buffer[23:0]};
                                    state <= SEND_REPLY;
                                end
                            endcase
                            payload_index <= payload_index + 1'b1;
                        end
                    end
                    SEND_REPLY: begin
                        if (tx_start) begin
                            if (response_index == response_last)
                                state <= WAIT_CMD;
                            else
                                response_index <= response_index + 1'b1;
                        end
                    end
                    default:
                        state <= WAIT_CMD;
                endcase
            end
        end
    end
endmodule
