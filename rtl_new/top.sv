module top #(parameter integer CLKS_PER_BIT = 868, parameter TEAM_FILE = "teams_2025.mem", parameter PROB_FILE = "probability.mem") (input logic clk, reset, rx, output logic tx, busy, done);
    logic [7:0] rx_data, tx_data;
    logic rx_valid, framing_error, tx_start, tx_busy;
    logic sim_start, load_en;
    logic [5:0] load_addr, load_team_id, read_addr;
    logic [31:0] num_simulations, win_count, total_simulations;

    // Assert reset asynchronously and release it synchronously.
    (* ASYNC_REG = "TRUE" *)
    logic [1:0] reset_pipe = 2'b11;

    logic internal_reset;

    always_ff @(posedge clk or posedge reset) begin
        if (reset)
            reset_pipe <= 2'b11;
        else
            reset_pipe <= {reset_pipe[0], 1'b0};
    end

    assign internal_reset = reset_pipe[1];
    
    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) receiver (.clk(clk), .reset(internal_reset), .rx(rx), .rx_data(rx_data), .rx_valid(rx_valid), .framing_error(framing_error));
    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) transmitter (.clk(clk), .reset(internal_reset), .tx_start(tx_start), .tx_data(tx_data), .tx(tx), .tx_busy(tx_busy));
    uart_ctrl command_unit (.clk(clk), .reset(internal_reset), .rx_valid(rx_valid), .framing_error(framing_error), .tx_busy(tx_busy), .sim_busy(busy), .sim_done(done), .rx_data(rx_data), .win_count(win_count), .total_simulations(total_simulations), .tx_start(tx_start), .sim_start(sim_start), .load_en(load_en), .tx_data(tx_data), .load_addr(load_addr), .load_team_id(load_team_id), .read_addr(read_addr), .num_simulations(num_simulations));
    simulation_ctrl #(.TEAM_FILE(TEAM_FILE), .PROB_FILE(PROB_FILE)) simulation (.clk(clk), .reset(internal_reset), .start(sim_start), .load_en(load_en), .load_addr(load_addr), .load_team_id(load_team_id), .read_addr(read_addr), .num_simulations(num_simulations), .win_count(win_count), .total_simulations(total_simulations), .busy(busy), .done(done));
endmodule
