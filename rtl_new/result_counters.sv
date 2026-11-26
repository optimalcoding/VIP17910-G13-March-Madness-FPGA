module result_counters (
    input  logic        clk,
    input  logic        reset,
    input  logic        clear,
    input  logic        tournament_done,
    input  logic [5:0]  champion_id,
    input  logic [5:0]  read_addr,
    output logic [31:0] win_count,
    output logic [31:0] total_simulations
);
    logic [31:0] counts [0:63];

    assign win_count = counts[read_addr];

    // Each counter reads its own value, avoiding an indexed read
    // multiplexer ahead of the incrementer.
    for (genvar team = 0; team < 64; team++) begin : gen_team_counter
        localparam logic [5:0] TEAM_ID = team;
        always_ff @(posedge clk or posedge reset) begin
            if (reset)
                counts[team] <= 32'd0;
            else if (clear)
                counts[team] <= 32'd0;
            else if (tournament_done && champion_id == TEAM_ID)
                counts[team] <= counts[team] + 32'd1;
        end
    end

    always_ff @(posedge clk or posedge reset) begin
        if (reset)
            total_simulations <= 32'd0;
        else if (clear)
            total_simulations <= 32'd0;
        else if (tournament_done)
            total_simulations <= total_simulations + 32'd1;
    end
endmodule
