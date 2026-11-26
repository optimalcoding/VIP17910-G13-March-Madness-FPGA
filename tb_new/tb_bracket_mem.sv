`timescale 1ns/1ps
module tb_bracket_mem;
    logic clk;
    logic [5:0] read_addr_a;
    logic [5:0] read_addr_b;
    logic [5:0] team_a_id;
    logic [5:0] team_b_id;
    logic write_en;
    logic [5:0] write_addr;
    logic [5:0] write_data;
    bracket_mem dut (
        .clk(clk),
        .read_addr_a(read_addr_a),
        .read_addr_b(read_addr_b),
        .team_a_id(team_a_id),
        .team_b_id(team_b_id),
        .write_en(write_en),
        .write_addr(write_addr),
        .write_data(write_data)
    );
    always #5 clk = ~clk;
    task automatic write_team(
        input logic [5:0] addr,
        input logic [5:0] id
    );
        @(negedge clk);
        write_en = 1;
        write_addr = addr;
        write_data = id;

        @(negedge clk);
        write_en = 0;
    endtask

    initial begin
        clk = 0;
        write_en = 0;
        write_addr = 0;
        write_data = 0;
        read_addr_a = 0;
        read_addr_b = 0;
        // Test 1: Initialize all 64 locations
        for (int i = 0; i < 64; i++) begin
            write_team(i[5:0], i[5:0]);
        end
        $display("Memory initialized");

        // Test 2: Verify all memory locations
        for (int i = 0; i < 64; i = i + 2) begin
            read_addr_a = 6'(i);
            read_addr_b = 6'(i + 1);
            #1;
            if (team_a_id !== 6'(i))
                $fatal(1, "Port A read failed");
            if (team_b_id !== 6'(i + 1))
                $fatal(1, "Port B read failed");
        end
        $display("Test 2 passed: Both read ports");

        // Test 3: Store a winning team
        // Assume Team 15 defeated Team 0
        write_team(6'd0, 6'd15);
        read_addr_a = 6'd0;
        #1;
        if (team_a_id !== 6'd15)
            $fatal(1, "Overwrite failed");
        $display("Test 3 passed: Store winner");

        // Test 4: Disable writing
        @(negedge clk);
        write_en = 0;
        write_addr = 6'd0;
        write_data = 6'd50;

        @(posedge clk);
        #1;
        if (team_a_id !== 6'd15)
            $fatal(1, "Write enable failed");
        $display("Test 4 passed: Write enable");

        $display("ALL BRACKET MEMORY TESTS PASSED");
        $finish;
    end
endmodule