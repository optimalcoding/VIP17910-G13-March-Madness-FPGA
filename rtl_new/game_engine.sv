module game_engine #(
    parameter TEAM_FILE = "teams_2025.mem",
    parameter PROB_FILE = "probability.mem"
) (
    input  logic clk, reset, start,
    input  logic [5:0] team_a_id, team_b_id,
    output logic [5:0] winner_id,
    output logic busy, done
);
    typedef enum logic [3:0] {
        IDLE, READ, PRODUCTS, PAIRS, GROUPS,
        STRENGTH, DIFFERENCE, PROBABILITY, CAPTURE
    } state_t;
    state_t state;

    logic [5:0] saved_a_id, saved_b_id;
    logic [63:0] stats_a, stats_b;
    logic [15:0] products_a [0:6];
    logic [15:0] products_b [0:6];
    logic [15:0] pairs_a [0:3];
    logic [15:0] pairs_b [0:3];
    logic [15:0] groups_a [0:1];
    logic [15:0] groups_b [0:1];
    logic [15:0] strength_a, strength_b;
    logic signed [16:0] strength_diff;
    logic [16:0] probability, probability_comb;
    logic [15:0] random_value;
    logic [5:0] selected_winner;
    logic prng_enable;

    team_stats_mem #(.MEM_FILE(TEAM_FILE)) stats_mem (
        .clk(clk), .team_a_id(saved_a_id), .team_b_id(saved_b_id),
        .team_a_stats(stats_a), .team_b_stats(stats_b)
    );
    probability_lut #(.MEM_FILE(PROB_FILE)) probability_unit (
        .strength_diff(strength_diff), .probability(probability_comb)
    );
    prng random_unit (
        .clk(clk), .reset(reset), .enable(prng_enable),
        .random_value(random_value)
    );
    winner_select winner_unit (
        .team_a_id(saved_a_id), .team_b_id(saved_b_id),
        .probability(probability), .random_value(random_value),
        .winner_id(selected_winner)
    );

    assign busy = (state != IDLE);
    assign prng_enable = (state == CAPTURE);

    // All intermediate values fit in 16 bits: maximum strength is 25500.
    // The zero-weight net-efficiency byte [47:40] is intentionally omitted.
    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= IDLE;
            saved_a_id <= 0;
            saved_b_id <= 0;
            winner_id <= 0;
            done <= 0;
            strength_a <= 0;
            strength_b <= 0;
            strength_diff <= 0;
            probability <= 0;
            for (int i = 0; i < 7; i++) begin
                products_a[i] <= 0;
                products_b[i] <= 0;
            end
            for (int i = 0; i < 4; i++) begin
                pairs_a[i] <= 0;
                pairs_b[i] <= 0;
            end
            for (int i = 0; i < 2; i++) begin
                groups_a[i] <= 0;
                groups_b[i] <= 0;
            end
        end else begin
            done <= 0;
            case (state)
                IDLE: begin
                    if (start) begin
                        saved_a_id <= team_a_id;
                        saved_b_id <= team_b_id;
                        state <= READ;
                    end
                end
                // The synchronous ROM captures the saved IDs at this edge.
                READ: state <= PRODUCTS;
                PRODUCTS: begin
                    products_a[0] <= stats_a[63:56] * 16'd20;
                    products_b[0] <= stats_b[63:56] * 16'd20;
                    products_a[1] <= stats_a[55:48] * 16'd20;
                    products_b[1] <= stats_b[55:48] * 16'd20;
                    products_a[2] <= stats_a[39:32] * 16'd18;
                    products_b[2] <= stats_b[39:32] * 16'd18;
                    products_a[3] <= stats_a[31:24] * 16'd12;
                    products_b[3] <= stats_b[31:24] * 16'd12;
                    products_a[4] <= stats_a[23:16] * 16'd9;
                    products_b[4] <= stats_b[23:16] * 16'd9;
                    products_a[5] <= stats_a[15:8] * 16'd6;
                    products_b[5] <= stats_b[15:8] * 16'd6;
                    products_a[6] <= stats_a[7:0] * 16'd15;
                    products_b[6] <= stats_b[7:0] * 16'd15;
                    state <= PAIRS;
                end
                PAIRS: begin
                    for (int i = 0; i < 3; i++) begin
                        pairs_a[i] <= products_a[2*i] + products_a[2*i+1];
                        pairs_b[i] <= products_b[2*i] + products_b[2*i+1];
                    end
                    pairs_a[3] <= products_a[6];
                    pairs_b[3] <= products_b[6];
                    state <= GROUPS;
                end
                GROUPS: begin
                    for (int i = 0; i < 2; i++) begin
                        groups_a[i] <= pairs_a[2*i] + pairs_a[2*i+1];
                        groups_b[i] <= pairs_b[2*i] + pairs_b[2*i+1];
                    end
                    state <= STRENGTH;
                end
                STRENGTH: begin
                    strength_a <= groups_a[0] + groups_a[1];
                    strength_b <= groups_b[0] + groups_b[1];
                    state <= DIFFERENCE;
                end
                DIFFERENCE: begin
                    strength_diff <= $signed({1'b0, strength_a})
                                   - $signed({1'b0, strength_b});
                    state <= PROBABILITY;
                end
                PROBABILITY: begin
                    probability <= probability_comb;
                    state <= CAPTURE;
                end
                CAPTURE: begin
                    // Use the current PRNG value, then advance once at this edge.
                    winner_id <= selected_winner;
                    done <= 1;
                    state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
