`timescale 1ns/1ps

module tb_probability_lut;

    logic signed [16:0] strength_diff;
    logic [16:0] probability;

    probability_lut dut (.strength_diff(strength_diff),.probability(probability));

    initial begin
        // Test 1: Equal strength
        strength_diff = 17'sd0;
        #10;
        if (probability !== 17'd32768)
            $fatal(1, "Test 1 failed");
        $display("Test 1 passed");

        // Test 2: Team A stronger
        strength_diff = 17'sd3000;
        #10;
        if (probability !== 17'd48218)
            $fatal(1, "Test 2 failed");
        $display("Test 2 passed");

        // Test 3: Team B stronger
        strength_diff = -17'sd3000;
        #10;
        if (probability !== 17'd17318)
            $fatal(1, "Test 3 failed");
        $display("Test 3 passed");

        // Test 4: Maximum strength difference
        strength_diff = 17'sd25500;
        #10;
        if (probability !== 17'd65523)
            $fatal(1, "Test 4 failed");
        $display("Test 4 passed");

        // Test 5: Negative maximum difference
        strength_diff = -17'sd25500;
        #10;
        if (probability !== 17'd13)
            $fatal(1, "Test 5 failed");
        $display("Test 5 passed");

        $display("ALL PROBABILITY LUT TESTS PASSED");
        $finish;
    end
endmodule