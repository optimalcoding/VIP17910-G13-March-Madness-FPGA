module probability_lut #(parameter MEM_FILE = "data/mem/probability.mem")(input  logic signed [16:0] strength_diff, output logic [16:0] probability);
    logic [16:0] mem [0:100];
    logic [16:0] magnitude;
    logic [6:0] index;
    logic [16:0] positive_probability;

    initial
        $readmemh(MEM_FILE, mem);

    assign magnitude = strength_diff[16] ? $unsigned(-strength_diff) : $unsigned(strength_diff);
    assign index = (magnitude >= 17'd25600) ? 7'd100 : magnitude[14:8] + {6'b0, magnitude[7]};
    assign positive_probability = mem[index];
    assign probability = strength_diff[16] ? 17'd65536 - positive_probability : positive_probability;
endmodule
