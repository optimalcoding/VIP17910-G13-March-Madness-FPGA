`timescale 1ns/1ps

module tb_uart_rx;
    localparam integer CLKS_PER_BIT = 16;
    logic clk, reset, rx, rx_valid, framing_error;
    logic [7:0] rx_data, expected [0:3];
    integer received_count, error_count;

    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) dut (.clk(clk), .reset(reset), .rx(rx), .rx_data(rx_data), .rx_valid(rx_valid), .framing_error(framing_error));

    always #5 clk = ~clk;

    task automatic send_bit(input logic value);
        rx = value;
        repeat (CLKS_PER_BIT) @(negedge clk);
    endtask

    task automatic send_byte(input logic [7:0] data, input logic stop_bit);
        send_bit(1'b0);
        for (int i = 0; i < 8; i++)
            send_bit(data[i]);
        send_bit(stop_bit);
    endtask

    always @(posedge clk) begin
        #1;
        if (!reset) begin
            if (rx_valid) begin
                if (received_count >= 4)
                    $fatal(1, "Unexpected received byte");
                if (rx_data !== expected[received_count])
                    $fatal(1, "Expected %h, received %h", expected[received_count], rx_data);
                $display("Received: %h", rx_data);
                received_count = received_count + 1;
            end
            if (framing_error)
                error_count = error_count + 1;
        end
    end

    initial begin
        clk = 0;
        reset = 1;
        rx = 1;
        received_count = 0;
        error_count = 0;
        expected[0] = 8'hA5;
        expected[1] = 8'h00;
        expected[2] = 8'hFF;
        expected[3] = 8'h3C;
        repeat (2) @(negedge clk);
        reset = 0;

        // Test 1: Idle
        repeat (32) @(negedge clk);
        if (received_count != 0 || error_count != 0)
            $fatal(1, "Idle test failed");
        $display("Test 1 passed");

        // Test 2: Receive one byte
        send_byte(8'hA5, 1'b1);
        if (received_count != 1)
            $fatal(1, "Single byte test failed");
        $display("Test 2 passed");

        // Test 3: Consecutive bytes
        send_byte(8'h00, 1'b1);
        send_byte(8'hFF, 1'b1);
        if (received_count != 3)
            $fatal(1, "Consecutive byte test failed");
        $display("Test 3 passed");

        // Test 4: False start
        rx = 0;
        repeat (2) @(negedge clk);
        rx = 1;
        repeat (32) @(negedge clk);
        if (received_count != 3 || error_count != 0)
            $fatal(1, "False start test failed");
        $display("Test 4 passed");

        // Test 5: Invalid stop bit
        send_byte(8'h55, 1'b0);
        rx = 1;
        repeat (32) @(negedge clk);
        if (error_count != 1 || received_count != 3)
            $fatal(1, "Framing error test failed");
        $display("Test 5 passed");

        // Test 6: Recovery
        send_byte(8'h3C, 1'b1);
        if (received_count != 4 || error_count != 1)
            $fatal(1, "Recovery test failed");
        $display("Test 6 passed");

        $display("ALL UART RX TESTS PASSED");
        $finish;
    end
endmodule