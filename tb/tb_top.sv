`timescale 1ns/1ps
module tb_top #(parameter TEAM_FILE = "data/mem/teams_2025.mem", parameter PROB_FILE = "data/mem/probability.mem");
    localparam integer CLKS_PER_BIT = 16, BIT_TIME = CLKS_PER_BIT * 10;
    logic clk, reset, rx, tx, busy, done;
    logic [7:0] captured [0:1023], sample;
    logic [31:0] expected [0:63], count_value;
    logic [63:0] sum;
    integer received_count, read_pos, champions, fd;

    top #(.CLKS_PER_BIT(CLKS_PER_BIT), .TEAM_FILE(TEAM_FILE), .PROB_FILE(PROB_FILE)) dut (.clk(clk), .reset(reset), .rx(rx), .tx(tx), .busy(busy), .done(done));
    always #5 clk = ~clk;

    // Independent UART monitor and championship scoreboard.
    initial begin
        wait (reset === 1'b0);
        forever begin
            @(negedge tx);
            #(BIT_TIME / 2);
            if (tx !== 0)
                $fatal(1, "Invalid TX start bit");
            for (int i = 0; i < 8; i++) begin
                #BIT_TIME;
                sample[i] = tx;
            end
            #BIT_TIME;
            if (tx !== 1)
                $fatal(1, "Invalid TX stop bit");
            if (received_count >= 1024)
                $fatal(1, "Reply buffer overflow");
            captured[received_count] = sample;
            received_count++;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            for (int i = 0; i < 64; i++)
                expected[i] = 0;
            champions = 0;
        end
        else if (dut.sim_start) begin
            for (int i = 0; i < 64; i++)
                expected[i] = 0;
            champions = 0;
        end
        else if (dut.simulation.tournament_done) begin
            if ($isunknown(dut.simulation.champion_id))
                $fatal(1, "Unknown champion ID");
            expected[dut.simulation.champion_id]++;
            champions++;
        end
    end

    task automatic send_byte(input logic [7:0] data);
        @(negedge clk);
        rx = 0;
        repeat (CLKS_PER_BIT) @(negedge clk);
        for (int i = 0; i < 8; i++) begin
            rx = data[i];
            repeat (CLKS_PER_BIT) @(negedge clk);
        end
        rx = 1;
        repeat (CLKS_PER_BIT) @(negedge clk);
    endtask

    task automatic get_byte(output logic [7:0] data);
        integer cycles;
        cycles = 0;
        while (received_count <= read_pos && cycles < 20000) begin
            @(negedge clk);
            cycles++;
        end
        if (received_count <= read_pos)
            $fatal(1, "UART response timeout at byte %0d", read_pos);
        data = captured[read_pos];
        read_pos++;
    endtask

    task automatic expect_byte(input logic [7:0] wanted);
        logic [7:0] data;
        get_byte(data);
        if (data !== wanted)
            $fatal(1, "Reply byte %0d: expected %h, got %h", read_pos - 1, wanted, data);
    endtask

    task automatic finish_reply;
        repeat (CLKS_PER_BIT + 2) @(negedge clk);
        if (received_count != read_pos || tx !== 1)
            $fatal(1, "Unexpected reply data");
    endtask

    task automatic set_count(input logic [31:0] n);
        send_byte(8'h02);
        for (int i = 0; i < 4; i++)
            send_byte(n[i*8 +: 8]);
        expect_byte(8'h06);
        finish_reply();
    endtask

    task automatic check_status(input logic [7:0] flags, input logic [31:0] n);
        send_byte(8'h05);
        expect_byte(8'h06);
        expect_byte(flags);
        for (int i = 0; i < 4; i++)
            expect_byte(n[i*8 +: 8]);
        finish_reply();
    endtask

    task automatic wait_for_batch;
        integer cycles;
        cycles = 0;
        while (busy && cycles < 10000) begin
            @(negedge clk);
            cycles++;
        end
        if (busy !== 0)
            $fatal(1, "Simulation batch timeout");
        repeat (2) @(negedge clk);
    endtask

    task automatic check_results(input logic [31:0] n);
        logic [7:0] data;
        sum = 0;
        send_byte(8'h04);
        expect_byte(8'h06);
        for (int i = 0; i < 64; i++) begin
            for (int j = 0; j < 4; j++) begin
                get_byte(data);
                count_value[j*8 +: 8] = data;
            end
            if (count_value !== expected[i])
                $fatal(1, "Team %0d: expected %0d, received %0d", i, expected[i], count_value);
            sum = sum + {32'd0, count_value};
            if (count_value != 0)
                $display("Team %0d: %0d wins", i, count_value);
        end
        finish_reply();
        if (sum !== {32'd0, n} || champions != int'(n))
            $fatal(1, "Incorrect total championship count");
    endtask

    initial begin
        clk = 0;
        reset = 1;
        rx = 1;
        received_count = 0;
        read_pos = 0;
        fd = $fopen(TEAM_FILE, "r");
        if (fd == 0)
            $fatal(1, "Missing team memory: %s", TEAM_FILE);
        $fclose(fd);
        fd = $fopen(PROB_FILE, "r");
        if (fd == 0)
            $fatal(1, "Missing probability memory: %s", PROB_FILE);
        $fclose(fd);
        repeat (4) @(negedge clk);
        reset = 0;

        send_byte(8'h03);
        expect_byte(8'h15);
        finish_reply();
        check_status(8'h00, 32'd0);
        $display("Test 1 passed: Reset and invalid start");

        // Synthetic bracket order, not the historical NCAA matchup order.
        send_byte(8'h01);
        for (int i = 0; i < 64; i++)
            send_byte(8'(63 - i));
        expect_byte(8'h06);
        finish_reply();
        check_status(8'h04, 32'd0);
        $display("Test 2 passed: Serial bracket loading");

        set_count(32'd2);
        send_byte(8'h03);
        expect_byte(8'h06);
        finish_reply();
        wait_for_batch();
        check_status(8'h06, 32'd2);
        check_results(32'd2);
        $display("Test 3 passed: Two tournaments and all championship counts");

        set_count(32'd0);
        send_byte(8'h03);
        expect_byte(8'h06);
        finish_reply();
        wait_for_batch();
        check_status(8'h06, 32'd0);
        check_results(32'd0);
        $display("Test 4 passed: Zero-tournament batch clears results");

        $display("ALL TOP LEVEL TESTS PASSED");
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "Global timeout");
    end
endmodule
