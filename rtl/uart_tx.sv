module uart_tx #(parameter integer CLKS_PER_BIT = 868) (input logic clk, reset, tx_start, input logic [7:0] tx_data, output logic tx, tx_busy);
    localparam integer CNT_WIDTH = (CLKS_PER_BIT > 1) ? $clog2(CLKS_PER_BIT) : 1;
    localparam logic [CNT_WIDTH-1:0] BIT_LAST = CNT_WIDTH'(CLKS_PER_BIT - 1);
    typedef enum logic [1:0] {IDLE, START, DATA, STOP} state_t;
    state_t state;
    logic [CNT_WIDTH-1:0] clk_count;
    logic [2:0] bit_index;
    logic [7:0] data_reg;

    assign tx_busy = (state != IDLE);

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= IDLE;
            clk_count <= 0;
            bit_index <= 0;
            data_reg <= 0;
            tx <= 1;
        end
        else begin
            case (state)
                IDLE: begin
                    clk_count <= 0;
                    bit_index <= 0;
                    tx <= 1;
                    if (tx_start) begin
                        data_reg <= tx_data;
                        tx <= 0;
                        state <= START;
                    end
                end
                START: begin
                    if (clk_count == BIT_LAST) begin
                        clk_count <= 0;
                        tx <= data_reg[0];
                        state <= DATA;
                    end
                    else
                        clk_count <= clk_count + 1'b1;
                end
                DATA: begin
                    if (clk_count == BIT_LAST) begin
                        clk_count <= 0;
                        if (bit_index == 3'd7) begin
                            tx <= 1;
                            state <= STOP;
                        end
                        else begin
                            bit_index <= bit_index + 1'b1;
                            tx <= data_reg[bit_index + 3'd1];
                        end
                    end
                    else
                        clk_count <= clk_count + 1'b1;
                end
                STOP: begin
                    if (clk_count == BIT_LAST) begin
                        clk_count <= 0;
                        state <= IDLE;
                    end
                    else
                        clk_count <= clk_count + 1'b1;
                end
                default: begin
                    state <= IDLE;
                    tx <= 1;
                end
            endcase
        end
    end
endmodule
