import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"

YEARS = [
    2016, 2017, 2018, 2019,
    2021, 2022, 2023, 2024, 2025
]

for kind in ["raw", "weighted"]:

    files = [
        OUTPUT / f"teams_{year}_{kind}.csv"
        for year in YEARS
    ]

    frames = [pd.read_csv(file) for file in files]

    # Ensure consistent column names across seasons
    for frame in frames:
        if set(frame.columns) != set(frames[0].columns):
            raise ValueError("Inconsistent CSV columns")

    combined = pd.concat(frames, ignore_index=True)

    assert len(combined) == len(YEARS) * 64
    assert (combined.groupby("season").size() == 64).all()
    assert not combined.isna().any().any()
    assert not combined.duplicated(
        subset=["season", "team_id"]
    ).any()

    combined.to_csv(
        OUTPUT / f"all_teams_{kind}.csv",
        index=False
    )

    print(f"\n{kind.upper()} DATASET")
    print(combined.groupby("season").size())
    print("Total teams:", len(combined))
    print("Missing values:", combined.isna().sum().sum())