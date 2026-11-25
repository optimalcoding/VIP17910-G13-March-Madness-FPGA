`timescale 1ns/1ps
module tb_result_counters;
    logic clk, reset, clear, tournament_done;
    logic [5:0] champion_id, read_addr;
    logic [31:0] win_count, total_simulations;

    result_counters dut (.clk(clk), .reset(reset), .clear(clear), .tournament_done(tournament_done), .champion_id(champion_id), .read_addr(read_addr), .win_count(win_count), .total_simulations(total_simulations));

    always #5 clk = ~clk;

    task automatic record_winner(input logic [5:0] id);
        @(negedge clk);
        champion_id = id;
        tournament_done = 1;
        @(negedge clk);
        tournament_done = 0;
    endtask

    task automatic check_count(input logic [5:0] id, input logic [31:0] expected);
        read_addr = id;
        #1;
        if (win_count !== expected)
            $fatal(1, "Team %0d: Expected %0d, Got %0d", id, expected, win_count);
    endtask

    initial begin
        clk = 0;
        reset = 1;
        clear = 0;
        tournament_done = 0;
        champion_id = 0;
        read_addr = 0;
        repeat (2) @(negedge clk);
        reset = 0;

        // Test 1: Reset
        for (int i = 0; i < 64; i++)
            check_count(6'(i), 32'd0);
        if (total_simulations !== 32'd0)
            $fatal(1, "Reset total failed");
        $display("Test 1 passed");

        // Test 2: First winner
        record_winner(6'd15);
        check_count(6'd15, 32'd1);
        $display("Test 2 passed");

        // Test 3: Repeated winner
        repeat (4)
            record_winner(6'd15);
        check_count(6'd15, 32'd5);
        $display("Test 3 passed");

        // Test 4: Multiple winners
        record_winner(6'd0);
        record_winner(6'd32);
        record_winner(6'd63);
        check_count(6'd0, 32'd1);
        check_count(6'd32, 32'd1);
        check_count(6'd63, 32'd1);
        check_count(6'd15, 32'd5);
        check_count(6'd20, 32'd0);
        $display("Test 4 passed");

        // Test 5: Total simulations
        if (total_simulations !== 32'd8)
            $fatal(1, "Incorrect total simulations");
        $display("Test 5 passed");

        // Test 6: Hold
        repeat (5) @(negedge clk);
        check_count(6'd15, 32'd5);
        if (total_simulations !== 32'd8)
            $fatal(1, "Unexpected increment");
        $display("Test 6 passed");

        // Test 7: Clear
        @(negedge clk);
        clear = 1;
        @(negedge clk);
        clear = 0;
        for (int i = 0; i < 64; i++)
            check_count(6'(i), 32'd0);
        if (total_simulations !== 32'd0)
            $fatal(1, "Clear failed");
        $display("Test 7 passed");

        $display("ALL RESULT COUNTER TESTS PASSED");
        $finish;
    end
endmodule