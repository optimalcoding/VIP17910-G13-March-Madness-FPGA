`timescale 1ns/1ps
module tb_game_engine;
    logic clk, reset, start, busy, done;
    logic [5:0] team_a_id, team_b_id, winner_id;

    game_engine dut ( .clk(clk), .reset(reset), .start(start), .team_a_id(team_a_id), .team_b_id(team_b_id), .winner_id(winner_id), .busy(busy), .done(done));

    always #5 clk = ~clk;

    task automatic play_game(input logic [5:0] a, b);
        integer cycles;
        begin
            // Supply inputs
            @(negedge clk);
            team_a_id = a;
            team_b_id = b;
            start = 1;

            // Turn off start after one clock cycle
            @(negedge clk);
            start = 0;

            cycles = 0;

            // Wait until game finishes
            while ((done !== 1'b1) && (cycles < 20)) begin
                @(posedge clk);
                #1;
                cycles = cycles + 1;
            end

            // Check for timeout
            if (done !== 1'b1)
                $fatal(1, "Game engine timeout");

            // Check whether winner is valid
            if ((winner_id !== a) &&
                (winner_id !== b))
                $fatal(1, "Invalid winner ID");
            // Display game result
            $display(
                "Team %0d vs Team %0d | Winner: %0d",
                a, b, winner_id
            );
            @(negedge clk);
        end
    endtask

    initial begin
        // Initialize inputs
        clk = 0;
        reset = 1;
        start = 0;
        team_a_id = 0;
        team_b_id = 0;

        // Reset the game engine
        repeat (2) @(negedge clk);
        reset = 0;

        $display("Starting game engine tests");

        // Test 1
        play_game(6'd0, 6'd15);

        // Test 2
        play_game(6'd1, 6'd14);

        // Test 3
        play_game(6'd2, 6'd13);

        // Test 4
        play_game(6'd3, 6'd12);

        // Test 5: Repeated matchup
        repeat (10) begin
            play_game(6'd0, 6'd15);
        end

        $display("ALL GAME ENGINE TESTS PASSED");

        $finish;
    end
endmodule