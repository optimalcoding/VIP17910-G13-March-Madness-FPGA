module team_stats_mem #(parameter MEM_FILE = "data/mem/teams_2025.mem")
(input logic clk, input logic [5:0] team_a_id, input logic [5:0] team_b_id, output logic [63:0] team_a_stats, output logic [63:0] team_b_stats);
    logic [63:0] mem [0:63];
    initial
        $readmemh(MEM_FILE, mem);
        
    always_ff @(posedge clk)
        team_a_stats <= mem[team_a_id];
        team_b_stats <= mem[team_b_id];

endmodule