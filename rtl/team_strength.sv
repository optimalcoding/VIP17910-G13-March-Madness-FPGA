module team_strength (input logic [63:0] stats, output logic [15:0] strength);
    assign strength = stats[63:56] * 16'd20
                    + stats[55:48] * 16'd20
                    + stats[39:32] * 16'd18
                    + stats[31:24] * 16'd12
                    + stats[23:16] * 16'd9
                    + stats[15:8] * 16'd6
                    + stats[7:0] * 16'd15;
endmodule