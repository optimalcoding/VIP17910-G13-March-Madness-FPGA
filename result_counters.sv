module result_counters (input logic clk, reset, clear, tournament_done, input logic [5:0] champion_id, read_addr, output logic [31:0] win_count, total_simulations);
    logic [31:0] counts [0:63];

    assign win_count = counts[read_addr];

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            for (int i = 0; i < 64; i++)
                counts[i] <= 32'd0;
            total_simulations <= 32'd0;
        end
        else if (clear) begin
            for (int i = 0; i < 64; i++)
                counts[i] <= 32'd0;
            total_simulations <= 32'd0;
        end
        else if (tournament_done) begin
            counts[champion_id] <= counts[champion_id] + 32'd1;
            total_simulations <= total_simulations + 32'd1;
        end
    end
endmodule