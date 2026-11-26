module simulation_ctrl #(parameter TEAM_FILE = "data/mem/teams_2025.mem", parameter PROB_FILE = "data/mem/probability.mem") (input logic clk, reset, start, load_en, input logic [5:0] load_addr, load_team_id, read_addr, input logic [31:0] num_simulations, output logic [31:0] win_count, total_simulations, output logic busy, done);
    typedef enum logic [1:0] {IDLE, CLEAR, ISSUE, WAIT_GAME} state_t;
    state_t state;
    logic [31:0] remaining;
    logic [5:0] champion_id;
    logic tournament_start, tournament_busy, tournament_done;
    logic clear_counts, bracket_load_en;

    tournament_ctrl #(.TEAM_FILE(TEAM_FILE), .PROB_FILE(PROB_FILE)) tournament (.clk(clk), .reset(reset), .start(tournament_start), .load_en(bracket_load_en), .load_addr(load_addr), .load_team_id(load_team_id), .champion_id(champion_id), .busy(tournament_busy), .done(tournament_done));

    result_counters counters (.clk(clk), .reset(reset), .clear(clear_counts), .tournament_done(tournament_done), .champion_id(champion_id), .read_addr(read_addr), .win_count(win_count), .total_simulations(total_simulations));

    assign busy = (state != IDLE);
    assign clear_counts = (state == CLEAR);
    assign tournament_start = (state == ISSUE) && !tournament_busy;
    assign bracket_load_en = (state == IDLE) && load_en && !start;

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= IDLE;
            remaining <= 0;
            done <= 0;
        end
        else begin
            done <= 0;
            case (state)
                IDLE: begin
                    if (start) begin
                        remaining <= num_simulations;
                        state <= CLEAR;
                    end
                end
                CLEAR: begin
                    if (remaining == 0) begin
                        done <= 1;
                        state <= IDLE;
                    end
                    else
                        state <= ISSUE;
                end
                ISSUE:
                    if (!tournament_busy)
                        state <= WAIT_GAME;
                WAIT_GAME: begin
                    if (tournament_done) begin
                        remaining <= remaining - 32'd1;
                        if (remaining == 32'd1) begin
                            done <= 1;
                            state <= IDLE;
                        end
                        else
                            state <= ISSUE;
                    end
                end
                default:
                    state <= IDLE;
            endcase
        end
    end
endmodule
