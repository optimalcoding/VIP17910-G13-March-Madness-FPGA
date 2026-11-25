`timescale 1ns/1ps

module tb_tournament_ctrl;
    logic clk;
    logic reset;
    logic start;
    logic load_en;
    logic [5:0] load_addr;
    logic [5:0] load_team_id;
    logic [5:0] champion_id;
    logic busy;
    logic done;
    logic [5:0] original_order [0:63];
    logic [5:0] expected [0:63];
    tournament_ctrl dut (
        .clk(clk),
        .reset(reset),
        .start(start),

        .load_en(load_en),
        .load_addr(load_addr),
        .load_team_id(load_team_id),

        .champion_id(champion_id),
        .busy(busy),
        .done(done)
    );
    always #5 clk = ~clk;
    task automatic run_tournament;

        integer games;
        integer game_idx;
        integer round_games;
        integer cycles;

        logic pending;

        begin
            games = 0;
            game_idx = 0;
            round_games = 32;
            cycles = 0;
            pending = 0;

            for (int i = 0; i < 64; i++)
                expected[i] = original_order[i];

            @(negedge clk);
            start = 1;

            @(negedge clk);
            start = 0;

            if (busy !== 1'b1)
                $fatal(1, "Tournament did not start");

            while ((done !== 1'b1) &&
                   (cycles < 1000)) begin
                @(posedge clk);

                if (dut.game_start) begin

                    if (pending || round_games == 0)
                        $fatal(1, "Unexpected game start");

                    if (dut.game_a_id !==
                        expected[2 * game_idx])
                        $fatal(1, "Incorrect Team A");

                    if (dut.game_b_id !==
                        expected[2 * game_idx + 1])
                        $fatal(1, "Incorrect Team B");

                    pending = 1;
                end

                if (dut.game_done) begin

                    if (!pending)
                        $fatal(1, "Unexpected game result");

                    if ((dut.game_winner !==
                         expected[2 * game_idx]) &&
                        (dut.game_winner !==
                         expected[2 * game_idx + 1]))
                        $fatal(1, "Invalid game winner");

                    expected[game_idx] = dut.game_winner;
                    games = games + 1;
                    game_idx = game_idx + 1;
                    pending = 0;
                    if (game_idx == round_games) begin
                        $display(
                            "Round completed: %0d games",
                            round_games
                        );
                        game_idx = 0;
                        round_games = round_games >> 1;
                    end
                end
                #1;
                cycles = cycles + 1;
            end

            if (done !== 1'b1)
                $fatal(1, "Tournament timeout");

            if (games != 63)
                $fatal(1, "Incorrect number of games");

            if (champion_id !== expected[0])
                $fatal(1, "Incorrect champion");

            $display("Total games: %0d", games);
            $display("Champion ID: %0d", champion_id);
            $display("Tournament test passed");
            @(posedge clk);
            #1;
            if (done !== 1'b0)
                $fatal(1, "Done pulse did not clear");
        end
    endtask

    initial begin
        clk = 0;
        reset = 1;
        start = 0;
        load_en = 0;
        load_addr = 0;
        load_team_id = 0;
        repeat (2) @(negedge clk);
        reset = 0;
        for (int i = 0; i < 64; i++) begin
            load_en = 1;
            load_addr = 6'(i);
            load_team_id = 6'(63 - i);
            original_order[i] = load_team_id;
            @(negedge clk);
        end
        load_en = 0;
        $display("Original bracket loaded");
        run_tournament();
        run_tournament();

        $display("ALL TOURNAMENT TESTS PASSED");
        $finish;
    end

endmodule