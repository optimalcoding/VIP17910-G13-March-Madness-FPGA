
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent

INPUT_FILE = BASE / "output/all_teams_weighted.csv"
MEM_FOLDER = BASE / "mem"

MEM_FOLDER.mkdir(exist_ok=True)


METRICS = [
    "adj_off_eff",
    "adj_def_eff",
    "net_eff_diff",
    "efg_pct",
    "to_pct",
    "orb_pct",
    "ftr",
    "seed_rank"
]

WEIGHTS = [
    20,
    20,
    0,
    18,
    12,
    9,
    6,
    15
]

BITS_PER_METRIC = 8
MAX_VALUE = (1 << BITS_PER_METRIC) - 1
TOTAL_BITS = len(METRICS) * BITS_PER_METRIC

assert sum(WEIGHTS) == 100


data = pd.read_csv(INPUT_FILE)

years = sorted(data["season"].unique())

print("Total team records:", len(data))
print("Available seasons:", years)


def quantize(value):

    if pd.isna(value) or not 0 <= value <= 1:
        raise ValueError(f"Invalid normalized value: {value}")

    return round(value * MAX_VALUE)

def pack_team(values):

    packed = 0

    for value in values:

        packed = (packed << BITS_PER_METRIC) | value

    return packed

for year in years:

    season_data = data[
        data["season"] == year
    ].sort_values("team_id")

    assert len(season_data) == 64
    assert season_data["team_id"].tolist() == list(range(64))

    mem_file = MEM_FOLDER / f"teams_{year}.mem"

    reference_file = (
        MEM_FOLDER / f"reference_{year}.csv"
    )

    reference_rows = []

    with open(mem_file, "w") as file:

        for _, team in season_data.iterrows():
            values = []

            for metric in METRICS:

                normalized = team[
                    f"{metric}_normalized"
                ]

                integer = quantize(normalized)

                values.append(integer)

            packed = pack_team(values)

            hex_value = f"{packed:016X}"

            file.write(hex_value + "\n")

            hardware_score = sum(
                value * weight
                for value, weight in zip(values, WEIGHTS)
            )

            reference = {
                "season": year,
                "team_id": team["team_id"],
                "team_name": team["team_name"],
                "hex_value": hex_value,
                "expected_rtl_score": hardware_score,
                "hardware_score_100": hardware_score / MAX_VALUE,
                "original_score": team["strength_score"]
            }

            for metric, value in zip(METRICS, values):
                reference[f"{metric}_uint8"] = value

            reference_rows.append(reference)

    # Save verification reference
    reference_df = pd.DataFrame(reference_rows)

    reference_df.to_csv(
        reference_file,
        index=False
    )

    print(f"\nSeason: {year}")
    print(f"Teams: {len(season_data)}")
    print(f"Memory file: {mem_file.name}")
    print(f"Reference file: {reference_file.name}")


print("\nPREPROCESSING COMPLETE")

print("Seasons:", len(years))
print("Bits per metric:", BITS_PER_METRIC)
print("Bits per team:", TOTAL_BITS)
print("Teams per season: 64")
print("Bytes per season:", 64 * TOTAL_BITS // 8)
print("Total memory files:", len(years))
