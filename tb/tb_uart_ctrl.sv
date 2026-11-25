`timescale 1ns/1ps
module tb_uart_ctrl;
    logic clk, reset, rx_valid, framing_error, tx_busy, sim_busy, sim_done, tx_start, sim_start, load_en;
    logic [7:0] rx_data, tx_data, captured [0:1023];
    logic [5:0] load_addr, load_team_id, read_addr, loaded [0:63];
    logic [31:0] win_count, total_simulations, num_simulations;
    integer tx_delay, tx_count, read_pos, load_count, start_count;

    uart_ctrl dut (.clk(clk), .reset(reset), .rx_valid(rx_valid), .framing_error(framing_error), .tx_busy(tx_busy), .sim_busy(sim_busy), .sim_done(sim_done), .rx_data(rx_data), .win_count(win_count), .total_simulations(total_simulations), .tx_start(tx_start), .sim_start(sim_start), .load_en(load_en), .tx_data(tx_data), .load_addr(load_addr), .load_team_id(load_team_id), .read_addr(read_addr), .num_simulations(num_simulations));
    always #5 clk = ~clk;
    assign tx_busy = (tx_delay != 0);
    assign win_count = 32'hA5000000 | {26'd0, read_addr};

    // Mock transmitter and bracket loader
    always @(posedge clk) begin
        if (reset) begin
            tx_delay <= 0;
            tx_count = 0;
            load_count = 0;
            start_count = 0;
        end
        else begin
            if (tx_delay != 0)
                tx_delay <= tx_delay - 1;
            else if (tx_start) begin
                captured[tx_count] = tx_data;
                tx_count = tx_count + 1;
                tx_delay <= 2;
            end
            if (load_en) begin
                loaded[load_addr] = load_team_id;
                load_count = load_count + 1;
            end
            if (sim_start)
                start_count = start_count + 1;
        end
    end

    task automatic send_byte(input logic [7:0] data);
        @(negedge clk);
        rx_data = data;
        rx_valid = 1;
        @(negedge clk);
        rx_valid = 0;
    endtask

    task automatic expect_byte(input logic [7:0] data);
        integer cycles;
        cycles = 0;
        while (tx_count <= read_pos && cycles < 100) begin
            @(negedge clk);
            cycles++;
        end
        if (tx_count <= read_pos)
            $fatal(1, "Reply timeout at byte %0d", read_pos);
        if (captured[read_pos] !== data)
            $fatal(1, "Byte %0d: expected %h, got %h", read_pos, data, captured[read_pos]);
        read_pos++;
    endtask

    task automatic expect_idle;
        repeat (5) @(negedge clk);
        if (tx_busy || tx_count != read_pos)
            $fatal(1, "Extra reply bytes or transmitter busy");
    endtask

    task automatic set_count(input logic [31:0] n);
        send_byte(8'h02);
        for (int i = 0; i < 4; i++)
            send_byte(n[i*8 +: 8]);
    endtask

    task automatic check_status(input logic [7:0] flags, input logic [31:0] n);
        send_byte(8'h05);
        expect_byte(8'h06);
        expect_byte(flags);
        for (int i = 0; i < 4; i++)
            expect_byte(n[i*8 +: 8]);
        expect_idle();
    endtask

    initial begin
        clk = 0;
        reset = 1;
        rx_valid = 0;
        framing_error = 0;
        sim_busy = 0;
        sim_done = 0;
        rx_data = 0;
        total_simulations = 0;
        read_pos = 0;
        repeat (2) @(negedge clk);
        reset = 0;

        // Reject start without a complete bracket and unknown commands.
        send_byte(8'h03);
        expect_byte(8'h15);
        expect_idle();
        send_byte(8'h99);
        expect_byte(8'h15);
        expect_idle();
        check_status(8'h00, 32'd0);
        if (start_count != 0)
            $fatal(1, "Invalid start accepted");
        $display("Test 1 passed: Reset and invalid commands");

        send_byte(8'h01);
        for (int i = 0; i < 64; i++)
            send_byte(8'(i == 63 ? 0 : i));
        expect_byte(8'h15);
        expect_idle();
        if (load_count != 63)
            $fatal(1, "Duplicate team was not rejected");
        check_status(8'h00, 32'd0);
        send_byte(8'h01);
        for (int i = 0; i < 64; i++)
            send_byte(8'(63 - i));
        expect_byte(8'h06);
        expect_idle();
        if (load_count != 127)
            $fatal(1, "Incorrect number of bracket writes");
        for (int i = 0; i < 64; i++)
            if (loaded[i] !== 6'(63 - i))
                $fatal(1, "Bracket mismatch at %0d", i);
        check_status(8'h04, 32'd0);
        $display("Test 2 passed: Bracket validation and loading");

        set_count(32'h12345678);
        expect_byte(8'h06);
        expect_idle();
        if (num_simulations !== 32'h12345678)
            $fatal(1, "Simulation count byte order failed");
        send_byte(8'h03);
        expect_byte(8'h06);
        expect_idle();
        if (start_count != 1)
            $fatal(1, "Start pulse failed");
        sim_busy = 1;
        total_simulations = 32'd7;
        check_status(8'h05, 32'd7);
        $display("Test 3 passed: Count, start and busy status");

        set_count(32'd10);
        expect_byte(8'h15);
        expect_idle();
        send_byte(8'h03);
        expect_byte(8'h15);
        expect_idle();
        send_byte(8'h04);
        expect_byte(8'h15);
        expect_idle();
        send_byte(8'h01);
        for (int i = 0; i < 64; i++)
            send_byte(8'(i));
        expect_byte(8'h15);
        expect_idle();
        if (num_simulations !== 32'h12345678 || start_count != 1 || load_count != 127)
            $fatal(1, "Busy command modified state");
        $display("Test 4 passed: Busy command rejection");

        @(negedge clk);
        sim_busy = 0;
        sim_done = 1;
        total_simulations = 32'h12345678;
        @(negedge clk);
        sim_done = 0;
        check_status(8'h06, 32'h12345678);
        send_byte(8'h04);
        expect_byte(8'h06);
        for (int i = 0; i < 64; i++) begin
            expect_byte(8'(i));
            expect_byte(8'h00);
            expect_byte(8'h00);
            expect_byte(8'hA5);
        end
        expect_idle();
        $display("Test 5 passed: All 64 result counts and byte order");

        @(negedge clk);
        framing_error = 1;
        @(negedge clk);
        framing_error = 0;
        expect_byte(8'h15);
        expect_idle();
        check_status(8'h06, 32'h12345678);
        $display("Test 6 passed: Framing error recovery");

        $display("ALL UART CONTROLLER TESTS PASSED");
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "Global timeout");
    end
endmodule
