`timescale 1ns/1ps

module tb_simulation_ctrl;
    logic clk, reset, start, load_en, busy, done;
    logic [5:0] load_addr, load_team_id, read_addr;
    logic [31:0] num_simulations, win_count, total_simulations;

    simulation_ctrl dut (.clk(clk), .reset(reset), .start(start), .load_en(load_en), .load_addr(load_addr), .load_team_id(load_team_id), .read_addr(read_addr), .num_simulations(num_simulations), .win_count(win_count), .total_simulations(total_simulations), .busy(busy), .done(done));

    always #5 clk = ~clk;

    task automatic run_batch(input logic [31:0] n);
        logic [31:0] expected [0:63];
        logic [31:0] sum;
        integer cycles;

        for (int i = 0; i < 64; i++)
            expected[i] = 0;
        cycles = 0;
        sum = 0;

        @(negedge clk);
        num_simulations = n;
        start = 1;
        @(negedge clk);
        start = 0;
        if (busy !== 1'b1)
            $fatal(1, "Simulation did not start");

        while ((done !== 1'b1) && (cycles < 10000)) begin
            @(posedge clk);
            if (dut.tournament_done)
                expected[dut.champion_id] = expected[dut.champion_id] + 1;
            #1;
            cycles = cycles + 1;
        end
        if (done !== 1'b1)
            $fatal(1, "Simulation timeout");
        if (busy !== 1'b0)
            $fatal(1, "Busy did not clear");
        if (total_simulations !== n)
            $fatal(1, "Incorrect total simulations");

        @(posedge clk);
        #1;
        if (done !== 1'b0)
            $fatal(1, "Done pulse did not clear");

        for (int i = 0; i < 64; i++) begin
            read_addr = 6'(i);
            #1;
            if (win_count !== expected[i])
                $fatal(1, "Team %0d: Incorrect championship count", i);
            sum = sum + win_count;
            if (win_count != 0)
                $display("Team %0d: %0d wins", i, win_count);
        end
        if (sum !== n)
            $fatal(1, "Incorrect sum of championship counts");

        $display("Batch passed: %0d tournaments, %0d cycles", n, cycles);
    endtask

    initial begin
        clk = 0;
        reset = 1;
        start = 0;
        load_en = 0;
        load_addr = 0;
        load_team_id = 0;
        read_addr = 0;
        num_simulations = 0;
        repeat (2) @(negedge clk);
        reset = 0;

        // Load original bracket
        for (int i = 0; i < 64; i++) begin
            load_en = 1;
            load_addr = 6'(i);
            load_team_id = 6'(i);
            @(negedge clk);
        end
        load_en = 0;

        // Test 1: Single tournament
        run_batch(32'd1);

        // Test 2: Multiple tournaments
        run_batch(32'd5);

        // Test 3: Zero tournaments
        run_batch(32'd0);

        // Test 4: Restart after clearing
        run_batch(32'd10);

        $display("ALL SIMULATION CONTROLLER TESTS PASSED");
        $finish;
    end
endmodule