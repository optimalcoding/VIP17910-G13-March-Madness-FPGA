module game_engine #(parameter TEAM_FILE = "data/mem/teams_2025.mem",parameter PROB_FILE = "data/mem/probability.mem")
(input logic clk, reset, start, input logic[5:0] team_a_id, team_b_id, output logic[5:0] winner_id, output logic busy, done);

    typedef enumlogic [1:0] {IDLE, READ, CAPTURE} state_t;

    state_t state, next_state;

    logic [5:0] saved_a_id;
    logic [5:0] saved_b_id;
    logic [63:0] stats_a;
    logic [63:0] stats_b;
    logic [15:0] strength_a;
    logic [15:0] strength_b;
    logic signed [16:0] strength_diff;
    logic [16:0] probability;
    logic [15:0] random_value;
    logic [5:0] selected_winner;
    logic prng_enable;

    team_stats_mem #(.MEM_FILE(TEAM_FILE))
    stats_mem(.clk(clk),.team_a_id(saved_a_id), .team_b_id(saved_b_id), .team_a_stats(stats_a), .team_b_stats(stats_b));
    matchup matchup_unit ( .team_a_stats(stats_a), .team_b_stats(stats_b), .strength_a(strength_a), .strength_b(strength_b), .strength_diff(strength_diff));
    probability_lut #(.MEM_FILE(PROB_FILE)) probability_unit(.strength_diff(strength_diff), .probability(probability));
    prng random_unit (.clk(clk), .reset(reset), .enable(prng_enable), .random_value(random_value));
    winner_select winner_unit (.team_a_id(saved_a_id), .team_b_id(saved_b_id), .probability(probability), .random_value(random_value), .winner_id(selected_winner));

    always_ff @(posedge clk or posedge reset) begin
        if (reset)
            state <= IDLE;
        else
            state <= next_state;
    end

    always_comb begin
        next_state = state;
        case (state)
            IDLE:
                if (start)
                    next_state = READ;
            READ:
                next_state = CAPTURE;
            CAPTURE:
                next_state = IDLE;
            default:
                next_state = IDLE;
        endcase
    end

    assign busy = (state != IDLE);
    assign prng_enable = (state == CAPTURE);

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            saved_a_id <= 6'd0;
            saved_b_id <= 6'd0;
            winner_id  <= 6'd0;
            done       <= 1'b0;
        end else begin
            done <= 1'b0;
            if (state == IDLE && start) begin
                saved_a_id <= team_a_id;
                saved_b_id <= team_b_id;
            end
            if (state == CAPTURE) begin
                winner_id <= selected_winner;
                done <= 1'b1;
            end
        end
    end
endmodule