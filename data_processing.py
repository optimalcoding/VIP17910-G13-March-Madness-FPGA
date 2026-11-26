import pandas as pd
import re
import sys
from pathlib import Path

YEAR = int(sys.argv[1])

BASE_FOLDER = Path(__file__).resolve().parent

INPUT_FILE = BASE_FOLDER / f"{YEAR}.csv"
NCAA_FOLDER = BASE_FOLDER
OUTPUT_FOLDER = BASE_FOLDER / "output"

OUTPUT_FOLDER.mkdir(exist_ok=True)

METRICS = {
    "adj_off_eff":  (20, 80, 140, True),
    "adj_def_eff":  (20, 80, 140, False),
    "net_eff_diff": (0, -30, 40, True),
    "efg_pct":      (18, 0.35, 0.65, True),
    "to_pct":       (12, 0.10, 0.30, False),
    "orb_pct":      (9, 0.15, 0.45, True),
    "ftr":          (6, 0.00, 0.70, True),
    "seed_rank":    (15, 1, 16, False)
}

assert sum(m[0] for m in METRICS.values()) == 100


raw = pd.read_csv(INPUT_FILE, header=None)

if raw.shape[1] < 31:
    raise ValueError("Unexpected Torvik CSV format")

if not (pd.to_numeric(raw[30]) == YEAR).all():
    raise ValueError("CSV season does not match YEAR")

stats = pd.DataFrame({
    "season": YEAR,
    "team_name": raw[0],
    "adj_off_eff": pd.to_numeric(raw[1]),
    "adj_def_eff": pd.to_numeric(raw[2]),
    "efg_pct": pd.to_numeric(raw[7]) / 100,
    "to_pct": pd.to_numeric(raw[11]) / 100,
    "orb_pct": pd.to_numeric(raw[13]) / 100,
    "ftr": pd.to_numeric(raw[9]) / 100
})

stats["net_eff_diff"] = (
    stats["adj_off_eff"] - stats["adj_def_eff"]
)

print(f"Original teams: {len(stats)}")

teams = pd.read_csv(
    NCAA_FOLDER / "MTeams.csv"
)

seeds = pd.read_csv(
    NCAA_FOLDER / "MNCAATourneySeeds.csv"
)

games = pd.read_csv(
    NCAA_FOLDER / "MNCAATourneyCompactResults.csv"
)

spellings = pd.read_csv(
    NCAA_FOLDER / "MTeamSpellings.csv",
    encoding="latin1"
)

seeds = seeds[seeds["Season"] == YEAR].copy()
games = games[games["Season"] == YEAR].copy()

seeds["slot"] = seeds["Seed"].str[:3]

if seeds["slot"].nunique() != 64:
    raise ValueError("Expected exactly 64 bracket slots")

selected_rows = []

for slot, group in seeds.groupby("slot"):

    if len(group) == 1:
        selected_rows.append(group.iloc[0])

    elif len(group) == 2:

        ids = group["TeamID"].tolist()

        play_in = games[
            games["WTeamID"].isin(ids)
            & games["LTeamID"].isin(ids)
        ]

        if len(play_in) != 1:
            raise ValueError(
                f"Cannot identify First Four winner: {slot}"
            )

        winner_id = play_in.iloc[0]["WTeamID"]

        selected_rows.append(
            group[group["TeamID"] == winner_id].iloc[0]
        )

    else:
        raise ValueError(f"Invalid bracket slot: {slot}")

tournament = pd.DataFrame(selected_rows)

assert len(tournament) == 64
assert tournament["TeamID"].nunique() == 64

tournament["seed_rank"] = (
    tournament["Seed"].str[1:3].astype(int)
)

tournament["region"] = (
    tournament["Seed"].str[0]
)

print("Tournament teams:", len(tournament))

def normalize_name(name):
    name = str(name).lower().strip()
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


name_lookup = {}

for _, row in teams.iterrows():

    name = normalize_name(row["TeamName"])

    name_lookup.setdefault(name, set()).add(
        int(row["TeamID"])
    )

for _, row in spellings.iterrows():

    name = normalize_name(row["TeamNameSpelling"])

    name_lookup.setdefault(name, set()).add(
        int(row["TeamID"])
    )

MANUAL_ALIASES = {
    "Cal State Bakersfield": "CS Bakersfield",
    "Cal St. Bakersfield": "CS Bakersfield",
    "CSU Bakersfield": "CS Bakersfield",
    "Texas A&M Corpus Christi": "TAM C. Christi",
    "Texas A&M-Corpus Christi": "TAM C. Christi",
    "Texas A&M CC": "TAM C. Christi",
    "Texas A&M-CC": "TAM C. Christi",
    "Texas A&M C.C.": "TAM C. Christi",
    "Texas A&M Corpus Chris": "TAM C. Christi",
    "Texas A&M Corpus Chris.": "TAM C. Christi",
    "Texas A&M-CC Islanders": "TAM C. Christi",
    "TAMU Corpus Christi": "TAM C. Christi"
}

manual_aliases = {
    normalize_name(k): normalize_name(v)
    for k, v in MANUAL_ALIASES.items()
}

tournament_ids = set(tournament["TeamID"])


def find_team_id(name):

    key = normalize_name(name)
    key = manual_aliases.get(key, key)

    candidates = name_lookup.get(key, set())
    candidates = candidates & tournament_ids

    if len(candidates) == 1:
        return next(iter(candidates))

    return None


stats["ncaa_team_id"] = stats["team_name"].apply(
    find_team_id
)


tournament = tournament.rename(
    columns={"TeamID": "ncaa_team_id"}
)

matched = stats.dropna(
    subset=["ncaa_team_id"]
).copy()

matched["ncaa_team_id"] = (
    matched["ncaa_team_id"].astype(int)
)

data = tournament[
    ["ncaa_team_id", "region", "seed_rank"]
].merge(
    matched,
    on="ncaa_team_id",
    how="left",
    validate="one_to_one"
)

missing = data[data["team_name"].isna()]

if not missing.empty:

    missing = missing.merge(
        teams,
        left_on="ncaa_team_id",
        right_on="TeamID",
        how="left"
    )

    print("\nUNMATCHED TEAMS:")

    print(
        missing[["TeamName", "ncaa_team_id"]]
        .to_string(index=False)
    )

    raise ValueError(
        "Add missing team names to MANUAL_ALIASES"
    )

data = data.sort_values(
    ["region", "seed_rank"]
).reset_index(drop=True)

data["team_id"] = range(64)


columns = [
    "season",
    "team_id",
    "ncaa_team_id",
    "team_name",
    "region",
    "seed_rank",
    "adj_off_eff",
    "adj_def_eff",
    "net_eff_diff",
    "efg_pct",
    "to_pct",
    "orb_pct",
    "ftr"
]

data = data[columns]

assert len(data) == 64
assert not data.isna().any().any()
assert data["team_name"].nunique() == 64
assert (data.groupby("region").size() == 16).all()

data.to_csv(
    OUTPUT_FOLDER / f"teams_{YEAR}_raw.csv",
    index=False
)


weighted_columns = []

for metric, settings in METRICS.items():

    weight, minimum, maximum, higher = settings

    outside = (
        (data[metric] < minimum)
        | (data[metric] > maximum)
    )

    if outside.any():
        print(
            f"Warning: {metric}: "
            f"{outside.sum()} values clipped"
        )

    if higher:
        normalized = (
            (data[metric] - minimum)
            / (maximum - minimum)
        )
    else:
        normalized = (
            (maximum - data[metric])
            / (maximum - minimum)
        )

    normalized = normalized.clip(0, 1)

    data[f"{metric}_normalized"] = normalized

    weighted_column = f"{metric}_weighted"

    data[weighted_column] = normalized * weight

    weighted_columns.append(weighted_column)


data["strength_score"] = data[
    weighted_columns
].sum(axis=1)

data["strength_rank"] = data[
    "strength_score"
].rank(
    ascending=False,
    method="min"
).astype(int)

assert data["strength_score"].between(0, 100).all()


data.to_csv(
    OUTPUT_FOLDER / f"teams_{YEAR}_weighted.csv",
    index=False,
    float_format="%.6f"
)


print("\nTOP 10 TEAMS:\n")

print(
    data.sort_values(
        "strength_score",
        ascending=False
    )[
        [
            "strength_rank",
            "team_name",
            "seed_rank",
            "strength_score"
        ]
    ].head(10).to_string(index=False)
)

print("\nDATA VALIDATION")
print("Season:", YEAR)
print("Total teams:", len(data))
print("Missing values:", data.isna().sum().sum())
print("Duplicate teams:", data["team_name"].duplicated().sum())

print("\nFiles generated:")
print(f"output/teams_{YEAR}_raw.csv")
print(f"output/teams_{YEAR}_weighted.csv")
