`timescale 1ns/1ps
module tb_prng;
    logic clk = 0;
    logic reset;
    logic enable;
    logic [15:0] random_value;
    prng dut (.clk(clk), .reset(reset), .enable(enable), .random_value(random_value));

    always #5 clk = ~clk;
    initial begin
        reset = 1;
        enable = 0;
        #10;
        if (random_value !== 16'hACE1)
            $fatal(1, "Reset failed");
        $display("Test 1 passed: Reset");

        @(negedge clk);
        reset = 0;
        enable = 1;

        @(posedge clk);
        #1;

        if (random_value !== 16'h59C3)
            $fatal(1, "First random value incorrect");

        $display("Test 2 passed: %h", random_value);

        // Test 3: Generate second random number
        @(posedge clk);
        #1;

        if (random_value !== 16'hB387)
            $fatal(1, "Second random value incorrect");

        $display("Test 3 passed: %h", random_value);

        // Test 4: Disable PRNG
        @(negedge clk);
        enable = 0;

        repeat (5) @(posedge clk);
        #1;

        if (random_value !== 16'hB387)
            $fatal(1, "Enable failed");

        $display("Test 4 passed: Hold value");

        // Test 5: Reset again
        @(negedge clk);
        reset = 1;
        #1;

        if (random_value !== 16'hACE1)
            $fatal(1, "Second reset failed");

        $display("Test 5 passed: Reset again");
        $display("ALL PRNG TESTS PASSED");
        $finish;
    end

endmodule