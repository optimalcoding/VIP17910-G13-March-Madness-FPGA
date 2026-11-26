module matchup(input logic[63:0] team_a_stats, team_b_stats,
               output logic[15:0] team_a_strength, team_b_strength,
               output logic signed[16:0] diff);

    team_strength a(team_a_stats, team_a_strength);
    team_strength b(team_b_stats, team_b_strength);
    
    assign diff = $signed({1'b0, team_a_strength}) - 
                  $signed({1'b0, team_b_strength});
endmodule
