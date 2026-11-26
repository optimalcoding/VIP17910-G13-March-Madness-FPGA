module uart_rx #(parameter integer CLKS_PER_BIT = 868) (input logic clk, reset, rx, output logic [7:0] rx_data, output logic rx_valid, framing_error);
    localparam integer CNT_WIDTH = $clog2(CLKS_PER_BIT);
    localparam logic [CNT_WIDTH-1:0] BIT_LAST = CNT_WIDTH'(CLKS_PER_BIT - 1), HALF_LAST = CNT_WIDTH'(CLKS_PER_BIT / 2 - 1);

    typedef enum logic [2:0] {IDLE, START, DATA, STOP, RECOVER} state_t;
    state_t state;

    (* ASYNC_REG = "TRUE" *)
    logic rx_sync1, rx_sync2;
    logic [CNT_WIDTH-1:0] clk_count;
    logic [2:0] bit_index;
    logic [7:0] data_reg;

    // Synchronize asynchronous input
    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            rx_sync1 <= 1;
            rx_sync2 <= 1;
        end
        else begin
            rx_sync1 <= rx;
            rx_sync2 <= rx_sync1;
        end
    end

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= IDLE;
            clk_count <= 0;
            bit_index <= 0;
            data_reg <= 0;
            rx_data <= 0;
            rx_valid <= 0;
            framing_error <= 0;
        end
        else begin
            rx_valid <= 0;
            framing_error <= 0;
            case (state)
                IDLE: begin
                    clk_count <= 0;
                    bit_index <= 0;
                    if (!rx_sync2)
                        state <= START;
                end
                START: begin
                    if (clk_count == HALF_LAST) begin
                        clk_count <= 0;
                        if (!rx_sync2)
                            state <= DATA;
                        else
                            state <= IDLE;
                    end
                    else
                        clk_count <= clk_count + 1'b1;
                end
                DATA: begin
                    if (clk_count == BIT_LAST) begin
                        clk_count <= 0;
                        data_reg[bit_index] <= rx_sync2;
                        if (bit_index == 3'd7)
                            state <= STOP;
                        else
                            bit_index <= bit_index + 1'b1;
                    end
                    else
                        clk_count <= clk_count + 1'b1;
                end
                STOP: begin
                    if (clk_count == BIT_LAST) begin
                        clk_count <= 0;
                        if (rx_sync2) begin
                            rx_data <= data_reg;
                            rx_valid <= 1;
                            state <= IDLE;
                        end
                        else begin
                            framing_error <= 1;
                            state <= RECOVER;
                        end
                    end
                    else
                        clk_count <= clk_count + 1'b1;
                end
                RECOVER:
                    if (rx_sync2)
                        state <= IDLE;
                default:
                    state <= IDLE;
            endcase
        end
    end
endmodule
