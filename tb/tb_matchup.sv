`timescale 1ns/1ps
module tb_matchup;
    logic [63:0] team_a_stats;
    logic [63:0] team_b_stats;
    logic [15:0] strength_a;
    logic [15:0] strength_b;
    logic signed [16:0] strength_diff;

    matchup dut (
        .team_a_stats(team_a_stats),
        .team_b_stats(team_b_stats),
        .strength_a(strength_a),
        .strength_b(strength_b),
        .strength_diff(strength_diff)
    );

    initial begin
        team_a_stats = 64'hFFFFFFFFFFFFFFFF;
        team_b_stats = 64'h0000000000000000;

        #10;
        if (strength_diff !== 17'sd25500)
            $fatal(1, "Test 1 failed");

        $display("Test 1 passed");
        team_a_stats = 64'h0000000000000000;
        team_b_stats = 64'hFFFFFFFFFFFFFFFF;

        #10;
        if (strength_diff !== -17'sd25500)
            $fatal(1, "Test 2 failed");

        $display("Test 2 passed");
        team_a_stats = 64'h8080808080808080;
        team_b_stats = 64'h8080808080808080;

        #10;
        if (strength_diff !== 17'sd0)
            $fatal(1, "Test 3 failed");

        $display("Test 3 passed");
        $display("ALL MATCHUP TESTS PASSED");
        $finish;
    end

endmodule