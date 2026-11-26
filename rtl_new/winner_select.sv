module winner_select (
    input  logic [5:0] team_a_id,
    input  logic [5:0] team_b_id,
    input  logic [16:0] probability,
    input  logic [15:0] random_value,
    output logic [5:0] winner_id
);
    logic a_wins;
    assign a_wins =
        {1'b0, random_value} < probability;
    assign winner_id =
        a_wins ? team_a_id : team_b_id;

endmodule
