import math
from pathlib import Path

SCALE = 3000
STEP = 256
ENTRIES = 101
folder = Path(__file__).resolve().parent / "mem"
folder.mkdir(parents=True, exist_ok=True)

with open(folder / "probability.mem", "w") as file:
    for i in range(ENTRIES):
        diff = i * STEP
        probability = 1 / (1 + math.exp(-diff / SCALE))
        threshold = round(probability * 65536)
        file.write(f"{threshold:05X}\n")
        
print("Probability LUT generated successfully")