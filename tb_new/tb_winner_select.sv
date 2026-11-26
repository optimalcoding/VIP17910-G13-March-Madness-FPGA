`timescale 1ns/1ps

module tb_winner_select;

    logic [5:0] team_a_id;
    logic [5:0] team_b_id;

    logic [16:0] probability;
    logic [15:0] random_value;

    logic [5:0] winner_id;

    winner_select dut (.team_a_id(team_a_id), .team_b_id(team_b_id), .probability(probability), .random_value(random_value), .winner_id(winner_id));

    initial begin

        team_a_id = 6'd10;
        team_b_id = 6'd25;

        // Test 1: Team A wins
        probability = 17'd40000;
        random_value = 16'd20000;

        #10;

        if (winner_id !== team_a_id)
            $fatal(1, "Test 1 failed");

        $display("Test 1 passed");

        // Test 2: Team B wins
        probability = 17'd40000;
        random_value = 16'd50000;

        #10;

        if (winner_id !== team_b_id)
            $fatal(1, "Test 2 failed");

        $display("Test 2 passed");

        // Test 3: Equal probability threshold
        probability = 17'd40000;
        random_value = 16'd40000;

        #10;

        if (winner_id !== team_b_id)
            $fatal(1, "Test 3 failed");

        $display("Test 3 passed");

        // Test 4: Team A has 0% probability
        probability = 17'd0;
        random_value = 16'd0;

        #10;

        if (winner_id !== team_b_id)
            $fatal(1, "Test 4 failed");

        $display("Test 4 passed");

        // Test 5: Team A has 100% probability
        probability = 17'd65536;
        random_value = 16'd65535;

        #10;

        if (winner_id !== team_a_id)
            $fatal(1, "Test 5 failed");

        $display("Test 5 passed");
        $display("ALL WINNER SELECT TESTS PASSED");
        $finish;
    end

endmodule