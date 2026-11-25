`timescale 1ns/1ps
module tb_uart_tx;
    localparam integer CLKS_PER_BIT = 16, BIT_TIME = CLKS_PER_BIT * 10;
    logic clk, reset, tx_start, tx, tx_busy;
    logic [7:0] tx_data, captured [0:7];
    logic [7:0] sample;
    integer received_count;

    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) dut (.clk(clk), .reset(reset), .tx_start(tx_start), .tx_data(tx_data), .tx(tx), .tx_busy(tx_busy));
    always #5 clk = ~clk;

    // Independent serial receiver
    initial begin
        wait (reset === 1'b0);
        forever begin
            @(negedge tx);
            #(BIT_TIME / 2);
            if (tx !== 0 || tx_busy !== 1)
                $fatal(1, "Invalid start bit");
            for (int i = 0; i < 8; i++) begin
                #BIT_TIME;
                if (tx_busy !== 1)
                    $fatal(1, "Busy cleared early");
                sample[i] = tx;
            end
            #BIT_TIME;
            if (tx !== 1 || tx_busy !== 1)
                $fatal(1, "Invalid stop bit");
            captured[received_count] = sample;
            received_count = received_count + 1;
        end
    end

    task automatic send_byte(input logic [7:0] data, input logic inject_start);
        integer cycles;
        @(negedge clk);
        if (tx_busy !== 0)
            $fatal(1, "TX unexpectedly busy");
        tx_data = data;
        tx_start = 1;
        @(negedge clk);
        tx_start = 0;
        if (tx_busy !== 1)
            $fatal(1, "TX did not start");
        tx_data = ~data;
        if (inject_start) begin
            repeat (3) @(negedge clk);
            tx_start = 1;
            @(negedge clk);
            tx_start = 0;
        end
        cycles = 0;
        while (tx_busy && cycles < 12 * CLKS_PER_BIT) begin
            @(negedge clk);
            cycles++;
        end
        if (tx_busy !== 0 || tx !== 1)
            $fatal(1, "TX timeout or idle error");
    endtask

    initial begin
        clk = 0;
        reset = 1;
        tx_start = 0;
        tx_data = 0;
        received_count = 0;
        repeat (2) @(negedge clk);
        reset = 0;
        if (tx !== 1 || tx_busy !== 0)
            $fatal(1, "Reset failed");
        $display("Test 1 passed: Reset");

        send_byte(8'hA5, 0);
        send_byte(8'h00, 0);
        send_byte(8'hFF, 0);
        if (received_count != 3 || captured[0] !== 8'hA5 || captured[1] !== 8'h00 || captured[2] !== 8'hFF)
            $fatal(1, "Data transmission failed");
        $display("Test 2 passed: Data and bit order");

        send_byte(8'h96, 1);
        repeat (12 * CLKS_PER_BIT) @(negedge clk);
        if (received_count != 4 || captured[3] !== 8'h96)
            $fatal(1, "Busy or data latch failed");
        $display("Test 3 passed: Ignore start while busy and latch data");

        $display("ALL UART TX TESTS PASSED");
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "Global timeout");
    end
endmodule
