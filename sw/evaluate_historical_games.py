"""Score the Python FPGA reference model on completed historical matchups."""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from march_madness_fpga import (
    DEFAULT_MEM_DIR,
    ProbabilityLUT,
    RTLReferenceSimulator,
    load_season_data,
)


def evaluate(results_file, mem_dir):
    probability_file = mem_dir / "probability.mem"
    if not probability_file.is_file():
        raise FileNotFoundError(probability_file)
    lut = ProbabilityLUT(probability_file)
    games_by_season = defaultdict(list)
    with results_file.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            games_by_season[int(row["season"])].append(
                (int(row["winner_team_id"]), int(row["loser_team_id"]))
            )
    if not games_by_season:
        raise ValueError(f"No completed games in {results_file}")

    for season, games in sorted(games_by_season.items()):
        teams, _ = load_season_data(mem_dir, season)
        model = RTLReferenceSimulator(teams, lut)
        counts = Counter()
        for winner, loser in games:
            # Ask for the real winner's probability, then check whether it
            # was favored. At exactly 50%, score the game as a coin flip.
            *_, probability = model.evaluate_matchup(winner, loser)
            if probability > 0x8000:
                counts["correct"] += 1
            elif probability == 0x8000:
                counts["tied"] += 1
            counts["games"] += 1
        yield season, counts


def print_summary(label, counts):
    games = counts["games"]
    correct = counts["correct"]
    tied = counts["tied"]
    missed = games - correct - tied
    accuracy = (correct + 0.5 * tied) / games
    print(
        f"{label}: {correct} correct, {missed} missed, {tied} tied "
        f"out of {games} games ({accuracy:.2%} with half credit for ties)"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_MEM_DIR.parent / "output" / "historical_results.csv",
    )
    parser.add_argument("--mem-dir", type=Path, default=DEFAULT_MEM_DIR)
    args = parser.parse_args()

    total = Counter()
    for season, counts in evaluate(args.results, args.mem_dir):
        print_summary(season, counts)
        total.update(counts)
    print_summary("Overall", total)


if __name__ == "__main__":
    main()
