module tournament_ctrl #(
    parameter TEAM_FILE = "data/mem/teams_2025.mem",
    parameter PROB_FILE = "data/mem/probability.mem"
)(  input logic clk,
    input logic reset,
    input logic start,
    input logic load_en,
    input logic [5:0] load_addr,
    input logic [5:0] load_team_id,
    output logic [5:0] champion_id,
    output logic busy,
    output logic done
);
    typedef enum logic [1:0] {
        IDLE,
        INIT,
        ISSUE,
        WAIT_GAME
    } state_t;
    state_t state;
    logic [5:0] original_bracket [0:63];
    logic [5:0] init_index;
    logic [4:0] game_index;
    logic [5:0] games_this_round;
    logic [5:0] read_addr_a;
    logic [5:0] read_addr_b;
    logic write_en;
    logic [5:0] write_addr;
    logic [5:0] write_data;
    logic [5:0] game_a_id;
    logic [5:0] game_b_id;
    logic [5:0] game_winner;
    logic game_start;
    logic game_busy;
    logic game_done;
    always_ff @(posedge clk) begin
        if (!reset && state == IDLE &&
            load_en && !start)
            original_bracket[load_addr] <= load_team_id;
    end

    bracket_mem bracket (
        .clk(clk),
        .read_addr_a(read_addr_a),
        .read_addr_b(read_addr_b),
        .team_a_id(game_a_id),
        .team_b_id(game_b_id),
        .write_en(write_en),
        .write_addr(write_addr),
        .write_data(write_data)
    );

    game_engine #(
        .TEAM_FILE(TEAM_FILE),
        .PROB_FILE(PROB_FILE)
    ) engine (
        .clk(clk),
        .reset(reset),
        .start(game_start),
        .team_a_id(game_a_id),
        .team_b_id(game_b_id),
        .winner_id(game_winner),
        .busy(game_busy),
        .done(game_done)
    );
    assign read_addr_a = {game_index, 1'b0};
    assign read_addr_b = {game_index, 1'b1};
    assign busy = (state != IDLE);
    assign game_start = (state == ISSUE) && !game_busy;


    always_comb begin
        write_en = 0;
        write_addr = 0;
        write_data = 0;
        case (state)
            INIT: begin
                write_en = 1;
                write_addr = init_index;
                write_data =
                    original_bracket[init_index];
            end
            WAIT_GAME: begin
                if (game_done) begin
                    write_en = 1;
                    write_addr = {1'b0, game_index};
                    write_data = game_winner;
                end
            end
            default: begin
                write_en = 0;
            end
        endcase
        if (reset)
            write_en = 0;
    end

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= IDLE;
            init_index <= 0;
            game_index <= 0;
            games_this_round <= 6'd32;
            champion_id <= 0;
            done <= 0;
        end else begin
            done <= 0;
            case (state)
                IDLE: begin
                    if (start) begin
                        init_index <= 0;
                        game_index <= 0;
                        games_this_round <= 6'd32;
                        state <= INIT;
                    end
                end
                INIT: begin
                    if (init_index == 6'd63)
                        state <= ISSUE;
                    else
                        init_index <= init_index + 1'b1;
                end
                ISSUE: begin
                    if (!game_busy)
                        state <= WAIT_GAME;
                end
                WAIT_GAME: begin
                    if (game_done) begin
                        // Championship completed
                        if (games_this_round == 6'd1) begin
                            champion_id <= game_winner;
                            done <= 1;
                            state <= IDLE;
                        end

                        // Current round completed
                        else if (game_index ==
                                 games_this_round - 6'd1) begin
                            game_index <= 0;
                            games_this_round <=
                                games_this_round >> 1;
                            state <= ISSUE;
                        end

                        // More games in current round
                        else begin
                            game_index <=
                                game_index + 1'b1;
                            state <= ISSUE;
                        end
                    end
                end
                default:
                    state <= IDLE;
            endcase
        end
    end
endmodule