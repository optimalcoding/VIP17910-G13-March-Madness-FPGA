module bracket_mem (input logic clk, write_en, input logic [5:0] read_addr_a, write_addr, write_data, read_addr_b, output logic [5:0] team_a_id, team_b_id);
    logic [5:0] mem [0:63];
    assign team_a_id = mem[read_addr_a];
    assign team_b_id = mem[read_addr_b];

    always_ff @(posedge clk) begin
        if (write_en)
            mem[write_addr] <= write_data;
    end
endmodule
