module prng(input logic clk, reset, enable, output logic[15:0] random_value);
    logic feedback;
    assign feedback = random_value[15] ^ random_value[13] ^ random_value[12] ^ random_value[10];
    always_ff @(posedge clk or posedge reset) begin
        if(reset)
            random_value <= 16'hACE1;
        else if(enable) begin
            random_value <= {random_value[14:0], feedback};
        end
    end
endmodule
