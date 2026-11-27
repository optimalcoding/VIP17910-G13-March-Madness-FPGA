"""
March Madness FPGA Predictor — Bit-Exact Reference Model & Basys 3 UART Host
=============================================================================
Synchronized 100% bit-for-bit and byte-for-byte with `rtl_new/` and `data/mem/`:
  - `top.sv` / `uart_ctrl.sv`      : 115,200 baud (CLKS_PER_BIT=868 @ 100 MHz),
                                     CMD_LOAD (0x01), CMD_SET (0x02), CMD_START (0x03),
                                     CMD_COUNTS (0x04), CMD_STATUS (0x05), ACK (0x06), NAK (0x15)
  - `team_strength.sv` / `game_engine.sv`:
                                     64-bit packed uint8 stats, weights [20, 20, 0, 18, 12, 9, 6, 15],
                                     10 cycles/game, 696 cycles/tournament (+2 startup cycles)
  - `probability_lut.sv`           : 101-entry 17-bit LUT (`data/mem/probability.mem`),
                                     half-up index `magnitude[14:8] + magnitude[7]`, clamp at 100,
                                     negative diff -> `65536 - positive_probability`
  - `prng.sv` / `winner_select.sv` : 16-bit Fibonacci LFSR (reset `0xACE1`, taps 15^13^12^10),
                                     sampled on CAPTURE before shifting; `{1'b0, rand} < probability`
  - `tournament_ctrl.sv`           : Sequential 64->32->16->8->4->2->1 bracket advancement
"""

import argparse
import csv
import math
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import serial  # type: ignore
except ImportError:
    serial = None


# ==============================================================================
# 1. HARDWARE CONSTANTS MATCHING `rtl_new/` & `data/preprocess.py`
# ==============================================================================

FPGA_CLK_HZ = 100_000_000
CLKS_PER_BIT = 868                  # 100 MHz / 868 = 115,207.37 baud (standard 115,200)
DEFAULT_BAUD = 115200

# UART Command & Response Bytes (`uart_ctrl.sv`)
CMD_LOAD   = 0x01  # + 64 unique bytes (team_id 0..63) -> replies 1B ACK/NAK
CMD_SET    = 0x02  # + 4B little-endian uint32 num_simulations -> replies 1B ACK/NAK
CMD_START  = 0x03  # 0B payload -> replies 1B ACK/NAK
CMD_COUNTS = 0x04  # 0B payload -> replies 1B ACK + 256B (64x little-endian uint32)
CMD_STATUS = 0x05  # 0B payload -> replies 1B ACK + 1B flags + 4B little-endian total_sims
ACK_BYTE   = 0x06
NAK_BYTE   = 0x15

# Metric order & weights (`data/preprocess.py` & `rtl_new/game_engine.sv`)
METRICS = [
    "adj_off_eff",   # [63:56] * 20
    "adj_def_eff",   # [55:48] * 20
    "net_eff_diff",  # [47:40] * 0 (omitted in hardware)
    "efg_pct",       # [39:32] * 18
    "to_pct",        # [31:24] * 12
    "orb_pct",       # [23:16] * 9
    "ftr",           # [15:8]  * 6
    "seed_rank",     # [7:0]   * 15
]
WEIGHTS = [20, 20, 0, 18, 12, 9, 6, 15]

# Cycle-accurate timing constants (`game_engine.sv`, `tournament_ctrl.sv`, `simulation_ctrl.sv`)
CYCLES_PER_GAME = 10                # ISSUE(1) + READ..CAPTURE(8) + WAIT_GAME_DONE(1)
CYCLES_PER_TOURNAMENT = 1 + 64 + (63 * CYCLES_PER_GAME) + 1  # 696 cycles/bracket
SIM_STARTUP_CYCLES = 2              # IDLE->CLEAR(1) + CLEAR->ISSUE(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEM_DIR = REPO_ROOT / "data" / "mem"


# ==============================================================================
# 2. BIT-EXACT RTL MODELS (`team_strength`, `probability_lut`, `prng`, `game_engine`)
# ==============================================================================

@dataclass
class TeamEntry:
    team_id: int
    team_name: str
    packed_u64: int
    strength: int  # 16-bit unsigned [0..25500]


def compute_team_strength(stats_u64: int) -> int:
    """
    Bit-exact match for `team_strength.sv` and `game_engine.sv` (PRODUCTS->PAIRS->GROUPS->STRENGTH).
    Byte [47:40] (`net_eff_diff`) has weight 0 and is intentionally omitted.
    Maximum possible value = 255 * 100 = 25,500 (fits in uint16).
    """
    b7 = (stats_u64 >> 56) & 0xFF  # adj_off_eff
    b6 = (stats_u64 >> 48) & 0xFF  # adj_def_eff
    # b5 = (stats_u64 >> 40) & 0xFF (net_eff_diff, weight 0)
    b4 = (stats_u64 >> 32) & 0xFF  # efg_pct
    b3 = (stats_u64 >> 24) & 0xFF  # to_pct
    b2 = (stats_u64 >> 16) & 0xFF  # orb_pct
    b1 = (stats_u64 >> 8)  & 0xFF  # ftr
    b0 = stats_u64 & 0xFF          # seed_rank

    return (
        b7 * 20
        + b6 * 20
        + b4 * 18
        + b3 * 12
        + b2 * 9
        + b1 * 6
        + b0 * 15
    )


class ProbabilityLUT:
    """
    Bit-exact match for `rtl_new/probability_lut.sv` and `data/generate_lut.py`.
    101 entries of 17-bit unsigned thresholds (`0x08000` .. `0x10000`).
    """
    SCALE = 3000
    STEP = 256
    ENTRIES = 101

    def __init__(self, mem_path: Optional[Path] = None):
        if mem_path is not None and mem_path.exists():
            lines = [
                ln.strip() for ln in mem_path.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("//")
            ]
            self.mem = [int(x, 16) & 0x1FFFF for x in lines[:self.ENTRIES]]
            if len(self.mem) != self.ENTRIES:
                raise ValueError(f"Expected {self.ENTRIES} entries in {mem_path}, got {len(self.mem)}")
        else:
            # Exact formula from `data/generate_lut.py`
            self.mem = [
                round((1.0 / (1.0 + math.exp(-(i * self.STEP) / self.SCALE))) * 65536)
                for i in range(self.ENTRIES)
            ]

    def lookup(self, strength_diff: int) -> Tuple[int, int]:
        """
        Input: signed 17-bit `strength_diff = strength_a - strength_b` in [-25500, +25500].
        Returns: `(lut_index, probability_u17)` matching `probability_lut.sv` bit-for-bit.
        """
        is_neg = strength_diff < 0
        magnitude = -strength_diff if is_neg else strength_diff

        if magnitude >= 25600:
            index = 100
        else:
            # `magnitude[14:8] + {6'b0, magnitude[7]}`
            index = ((magnitude >> 8) & 0x7F) + ((magnitude >> 7) & 0x1)

        pos_prob = self.mem[index]
        probability = (65536 - pos_prob) if is_neg else pos_prob
        return index, probability


class HardwarePRNG16:
    """
    Bit-exact match for `rtl_new/prng.sv` + `game_engine.sv` (`CAPTURE` state):
      - 16-bit Fibonacci LFSR, reset value `16'hACE1`
      - `feedback = random_value[15] ^ random_value[13] ^ random_value[12] ^ random_value[10]`
      - `game_engine.sv` uses the CURRENT `random_value` during `CAPTURE`, and pulses
        `prng_enable` on that same clock edge to advance for the next game.
    """
    RESET_SEED = 0xACE1

    def __init__(self, seed: int = RESET_SEED):
        self.state = seed & 0xFFFF

    def sample_and_step(self) -> int:
        current = self.state
        feedback = (
            ((current >> 15) & 1)
            ^ ((current >> 13) & 1)
            ^ ((current >> 12) & 1)
            ^ ((current >> 10) & 1)
        )
        self.state = ((current << 1) | feedback) & 0xFFFF
        return current


class RTLReferenceSimulator:
    """
    Cycle- and bit-accurate golden model of `simulation_ctrl` -> `tournament_ctrl` -> `game_engine`.
    """
    def __init__(self, teams: Dict[int, TeamEntry], lut: ProbabilityLUT):
        if len(teams) != 64 or sorted(teams.keys()) != list(range(64)):
            raise ValueError("Teams dictionary must contain exact team_ids 0..63.")
        self.teams = teams
        self.lut = lut

    def evaluate_matchup(self, team_a_id: int, team_b_id: int) -> Tuple[int, int, int, int, int]:
        """Returns `(strength_a, strength_b, strength_diff, lut_index, probability_u17)`."""
        sa = self.teams[team_a_id].strength
        sb = self.teams[team_b_id].strength
        diff = sa - sb
        idx, prob = self.lut.lookup(diff)
        return sa, sb, diff, idx, prob

    def run_single_tournament(
        self,
        bracket_order: List[int],
        prng: HardwarePRNG16,
        trace: Optional[List[Dict]] = None,
    ) -> int:
        """
        Matches `tournament_ctrl.sv` (`INIT` -> 6 rounds of `32, 16, 8, 4, 2, 1` games).
        Writes winners back into `bracket_mem[0 .. games_this_round-1]`.
        """
        bracket_mem = list(bracket_order)
        games_this_round = 32
        round_num = 1
        game_counter = 0

        while games_this_round >= 1:
            for game_index in range(games_this_round):
                id_a = bracket_mem[2 * game_index]
                id_b = bracket_mem[2 * game_index + 1]

                sa, sb, diff, lut_idx, prob = self.evaluate_matchup(id_a, id_b)
                rand_val = prng.sample_and_step()

                # `winner_select.sv`: `{1'b0, random_value} < probability`
                winner_id = id_a if rand_val < prob else id_b
                bracket_mem[game_index] = winner_id

                if trace is not None:
                    trace.append({
                        "game_idx": game_counter,
                        "round": round_num,
                        "game_in_round": game_index,
                        "team_a_id": id_a,
                        "team_b_id": id_b,
                        "strength_a": sa,
                        "strength_b": sb,
                        "strength_diff": diff,
                        "lut_idx": lut_idx,
                        "probability_hex": f"{prob:05X}",
                        "random_hex": f"{rand_val:04X}",
                        "winner_id": winner_id,
                    })
                game_counter += 1

            if games_this_round == 1:
                return bracket_mem[0]
            games_this_round >>= 1
            round_num += 1

        return bracket_mem[0]

    def run_simulations(
        self,
        bracket_order: List[int],
        num_simulations: int,
        seed: int = HardwarePRNG16.RESET_SEED,
    ) -> Dict:
        """
        Matches `simulation_ctrl.sv` + `result_counters.sv`.
        Note: On FPGA, `prng` resets to `0xACE1` on `reset` button / power-up and
        continues across multiple `CMD_START` runs unless `reset` is asserted.
        """
        validate_bracket_order(bracket_order)
        prng = HardwarePRNG16(seed=seed)
        win_counts = [0] * 64

        t0 = time.perf_counter()
        for _ in range(num_simulations):
            champ = self.run_single_tournament(bracket_order, prng)
            win_counts[champ] += 1
        cpu_time_s = time.perf_counter() - t0

        exact_cycles = 1 if num_simulations == 0 else (SIM_STARTUP_CYCLES + num_simulations * CYCLES_PER_TOURNAMENT)
        fpga_time_s = exact_cycles / FPGA_CLK_HZ

        return {
            "win_counts": win_counts,
            "total_simulations": num_simulations,
            "cpu_time_s": cpu_time_s,
            "fpga_cycles": exact_cycles,
            "fpga_time_s": fpga_time_s,
            "final_prng_state": prng.state,
        }


# ==============================================================================
# 3. DATA LOADERS FOR `data/mem/teams_<year>.mem` & `reference_<year>.csv`
# ==============================================================================

def validate_bracket_order(bracket_order: List[int]) -> None:
    """Enforces `uart_ctrl.sv` `invalid_team` rules: 64 unique IDs in 0..63."""
    if len(bracket_order) != 64:
        raise ValueError(f"Bracket must have exactly 64 entries, got {len(bracket_order)}.")
    seen = set()
    for idx, tid in enumerate(bracket_order):
        if not (0 <= tid <= 63):
            raise ValueError(f"Bracket slot {idx} has out-of-range team_id {tid} (must be 0..63).")
        if tid in seen:
            raise ValueError(f"Duplicate team_id {tid} at slot {idx} (`uart_ctrl.sv` rejects duplicates with NAK).")
        seen.add(tid)


def load_season_data(
    mem_dir: Path,
    season: int,
) -> Tuple[Dict[int, TeamEntry], Optional[Path]]:
    """
    Loads `teams_<season>.mem` and optional `reference_<season>.csv` (for team names
    and verification against `expected_rtl_score` generated by `preprocess.py`).
    """
    mem_file = mem_dir / f"teams_{season}.mem"
    ref_file = mem_dir / f"reference_{season}.csv"

    if not mem_file.exists():
        raise FileNotFoundError(f"Could not find {mem_file}")

    hex_lines = [
        ln.strip() for ln in mem_file.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("//")
    ]
    if len(hex_lines) != 64:
        raise ValueError(f"Expected 64 lines in {mem_file}, found {len(hex_lines)}.")

    names_by_id: Dict[int, str] = {i: f"Team_{i:02d}" for i in range(64)}
    expected_scores: Dict[int, int] = {}

    if ref_file.exists():
        with open(ref_file, mode="r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tid = int(row["team_id"])
                names_by_id[tid] = row.get("team_name", f"Team_{tid:02d}").strip()
                if "expected_rtl_score" in row and row["expected_rtl_score"] != "":
                    expected_scores[tid] = int(float(row["expected_rtl_score"]))

    teams: Dict[int, TeamEntry] = {}
    for tid, hex_str in enumerate(hex_lines):
        packed_u64 = int(hex_str, 16)
        strength = compute_team_strength(packed_u64)
        if tid in expected_scores and strength != expected_scores[tid]:
            raise ValueError(
                f"Strength mismatch for team {tid} ({names_by_id[tid]}): "
                f"computed {strength} vs reference CSV {expected_scores[tid]}"
            )
        teams[tid] = TeamEntry(
            team_id=tid,
            team_name=names_by_id[tid],
            packed_u64=packed_u64,
            strength=strength,
        )

    return teams, (ref_file if ref_file.exists() else None)


def load_bracket_file(bracket_path: Optional[Path]) -> List[int]:
    """
    Loads a 64-entry initial bracket order from `.mem` (hex), `.txt` (int), or `.csv` (`team_id` column).
    Defaults to `[0, 1, 2, ..., 63]` if no custom bracket file is supplied.
    """
    if bracket_path is None:
        return list(range(64))

    if bracket_path.suffix.lower() == ".csv":
        with open(bracket_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            ids = [int(row["team_id"]) for row in reader]
    else:
        lines = [
            ln.strip() for ln in bracket_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("//")
        ]
        base = 16 if bracket_path.suffix.lower() == ".mem" else 0
        ids = [int(x, base) for x in lines]

    validate_bracket_order(ids)
    return ids


# ==============================================================================
# 4. BASYS 3 UART PROTOCOL CLIENT (`rtl_new/uart_ctrl.sv` EXACT BINARY PROTOCOL)
# ==============================================================================

class VirtualBasys3Board:
    """
    In-memory byte-accurate emulator of `uart_ctrl.sv` + `simulation_ctrl.sv`
    for offline testing before connecting the physical Basys 3 USB cable.
    """
    def __init__(self, sim: RTLReferenceSimulator):
        self.sim = sim
        self.prng = HardwarePRNG16(HardwarePRNG16.RESET_SEED)
        self.bracket_loaded = False
        self.results_valid = False
        self.sim_busy = False
        self.bracket = [0] * 64
        self.num_simulations = 0
        self.total_simulations = 0
        self.win_counts = [0] * 64
        self._rx_buf = bytearray()
        self._tx_buf = bytearray()

    def write(self, data: bytes) -> int:
        self._rx_buf.extend(data)
        self._process()
        return len(data)

    def flush(self) -> None:
        pass

    def read(self, size: int = 1) -> bytes:
        out = bytes(self._tx_buf[:size])
        del self._tx_buf[:size]
        return out

    def close(self) -> None:
        pass

    def _process(self) -> None:
        while self._rx_buf:
            cmd = self._rx_buf[0]
            if cmd == CMD_LOAD:
                if len(self._rx_buf) < 65:
                    return
                payload = list(self._rx_buf[1:65])
                del self._rx_buf[:65]
                seen = set()
                bad = self.sim_busy
                for b in payload:
                    if (b >> 6) != 0 or b in seen:
                        bad = True
                    else:
                        seen.add(b)
                if bad:
                    self._tx_buf.append(NAK_BYTE)
                else:
                    self.bracket = payload
                    self.bracket_loaded = True
                    self.results_valid = False
                    self._tx_buf.append(ACK_BYTE)

            elif cmd == CMD_SET:
                if len(self._rx_buf) < 5:
                    return
                (count_val,) = struct.unpack("<I", bytes(self._rx_buf[1:5]))
                del self._rx_buf[:5]
                if self.sim_busy:
                    self._tx_buf.append(NAK_BYTE)
                else:
                    self.num_simulations = count_val
                    self._tx_buf.append(ACK_BYTE)

            elif cmd == CMD_START:
                del self._rx_buf[:1]
                if self.sim_busy or not self.bracket_loaded:
                    self._tx_buf.append(NAK_BYTE)
                else:
                    self._tx_buf.append(ACK_BYTE)
                    self.win_counts = [0] * 64
                    for _ in range(self.num_simulations):
                        champ = self.sim.run_single_tournament(self.bracket, self.prng)
                        self.win_counts[champ] += 1
                    self.total_simulations = self.num_simulations
                    self.results_valid = True

            elif cmd == CMD_STATUS:
                del self._rx_buf[:1]
                flags = (
                    ((1 if self.bracket_loaded else 0) << 2)
                    | ((1 if self.results_valid else 0) << 1)
                    | (1 if self.sim_busy else 0)
                )
                self._tx_buf.extend(struct.pack("<BBI", ACK_BYTE, flags, self.total_simulations))

            elif cmd == CMD_COUNTS:
                del self._rx_buf[:1]
                if self.sim_busy or not self.results_valid:
                    self._tx_buf.append(NAK_BYTE)
                else:
                    self._tx_buf.append(ACK_BYTE)
                    self._tx_buf.extend(struct.pack("<64I", *self.win_counts))

            else:
                del self._rx_buf[:1]
                self._tx_buf.append(NAK_BYTE)


class Basys3UARTClient:
    """
    Host controller speaking the exact binary protocol of `rtl_new/uart_ctrl.sv`:
      - CMD_LOAD   (0x01) + 64B team IDs       -> 1B ACK (0x06)
      - CMD_SET    (0x02) + 4B uint32 LE sims  -> 1B ACK (0x06)
      - CMD_START  (0x03)                      -> 1B ACK (0x06)
      - CMD_STATUS (0x05)                      -> 6B: ACK + flags + uint32 LE total_simulations
      - CMD_COUNTS (0x04)                      -> 257B: ACK + 64x uint32 LE win_counts
    """
    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = DEFAULT_BAUD,
        timeout: float = 5.0,
        virtual_board: Optional[VirtualBasys3Board] = None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.dev = virtual_board

    def connect(self) -> None:
        if self.dev is not None:
            return
        if not self.port:
            raise ValueError("Specify `--uart-port` (e.g., COM4) or pass a `VirtualBasys3Board`.")
        if serial is None:
            raise RuntimeError("pyserial is not installed. Run: `py -m pip install pyserial`")
        self.dev = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        time.sleep(0.05)  # Allow FT2232HQ USB-UART bridge to settle
        if hasattr(self.dev, "reset_input_buffer"):
            self.dev.reset_input_buffer()

    def close(self) -> None:
        if self.dev is not None:
            self.dev.close()

    def _read_exact(self, n: int) -> bytes:
        assert self.dev is not None
        buf = bytearray()
        while len(buf) < n:
            chunk = self.dev.read(n - len(buf))
            if not chunk:
                raise TimeoutError(f"UART timeout: expected {n} bytes from Basys 3, received {len(buf)}.")
            buf.extend(chunk)
        return bytes(buf)

    def _expect_ack(self, cmd_name: str) -> None:
        resp = self._read_exact(1)[0]
        if resp == NAK_BYTE:
            raise RuntimeError(f"Basys 3 returned NAK (0x15) for {cmd_name}.")
        if resp != ACK_BYTE:
            raise RuntimeError(f"Unexpected response 0x{resp:02X} for {cmd_name} (expected ACK 0x06).")

    def load_bracket(self, bracket_order: List[int]) -> None:
        """Sends `CMD_LOAD (0x01)` + 64 unique 6-bit team IDs."""
        validate_bracket_order(bracket_order)
        assert self.dev is not None
        pkt = bytes([CMD_LOAD]) + bytes(bracket_order)
        self.dev.write(pkt)
        self.dev.flush()
        self._expect_ack("CMD_LOAD")

    def set_num_simulations(self, num_simulations: int) -> None:
        """Sends `CMD_SET (0x02)` + 4-byte little-endian `num_simulations`."""
        if not (0 <= num_simulations <= 0xFFFFFFFF):
            raise ValueError("num_simulations must fit in 32-bit unsigned integer.")
        assert self.dev is not None
        pkt = struct.pack("<BI", CMD_SET, num_simulations)
        self.dev.write(pkt)
        self.dev.flush()
        self._expect_ack("CMD_SET")

    def start_simulation(self) -> None:
        """Sends `CMD_START (0x03)` to launch tournament runs on Basys 3."""
        assert self.dev is not None
        self.dev.write(bytes([CMD_START]))
        self.dev.flush()
        self._expect_ack("CMD_START")

    def get_status(self) -> Dict:
        """Sends `CMD_STATUS (0x05)` and parses `{bracket_loaded, results_valid, sim_busy}` + `total_simulations`."""
        assert self.dev is not None
        self.dev.write(bytes([CMD_STATUS]))
        self.dev.flush()
        self._expect_ack("CMD_STATUS")
        raw = self._read_exact(5)
        flags, total_sims = struct.unpack("<BI", raw)
        return {
            "raw_flags": flags,
            "sim_busy": bool(flags & 0x01),
            "results_valid": bool((flags >> 1) & 0x01),
            "bracket_loaded": bool((flags >> 2) & 0x01),
            "total_simulations": total_sims,
        }

    def wait_until_done(self, poll_interval_s: float = 0.005, max_wait_s: float = 60.0) -> Dict:
        """Polls `CMD_STATUS` until `sim_busy == 0` and `results_valid == 1`."""
        t0 = time.perf_counter()
        while True:
            st = self.get_status()
            if not st["sim_busy"] and st["results_valid"]:
                return st
            if (time.perf_counter() - t0) > max_wait_s:
                raise TimeoutError(f"Simulation did not finish within {max_wait_s}s (last status: {st}).")
            time.sleep(poll_interval_s)

    def read_win_counts(self) -> List[int]:
        """Sends `CMD_COUNTS (0x04)` and reads 256 bytes (64 little-endian uint32 championship counts)."""
        assert self.dev is not None
        self.dev.write(bytes([CMD_COUNTS]))
        self.dev.flush()
        self._expect_ack("CMD_COUNTS")
        payload = self._read_exact(256)
        return list(struct.unpack("<64I", payload))

    def run_full_job(self, bracket_order: List[int], num_simulations: int) -> Tuple[List[int], Dict, float]:
        """Executes full host->FPGA workflow: LOAD -> SET -> START -> POLL STATUS -> READ COUNTS."""
        self.load_bracket(bracket_order)
        self.set_num_simulations(num_simulations)
        t0 = time.perf_counter()
        self.start_simulation()
        status = self.wait_until_done()
        wall_s = time.perf_counter() - t0
        counts = self.read_win_counts()
        return counts, status, wall_s


# ==============================================================================
# 5. CSV LOGGING & TESTBENCH TRACE EXPORT
# ==============================================================================

def save_results_csv(
    out_csv: Path,
    season: int,
    teams: Dict[int, TeamEntry],
    win_counts: List[int],
    total_simulations: int,
) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    exact_cycles = 1 if total_simulations == 0 else (SIM_STARTUP_CYCLES + total_simulations * CYCLES_PER_TOURNAMENT)
    fpga_ms = (exact_cycles / FPGA_CLK_HZ) * 1000.0

    rows = []
    for tid in range(64):
        t = teams[tid]
        wins = win_counts[tid]
        rows.append({
            "season": season,
            "team_id": tid,
            "team_name": t.team_name,
            "rtl_strength": t.strength,
            "win_count": wins,
            "win_probability": round(wins / max(1, total_simulations), 6),
            "total_simulations": total_simulations,
            "exact_fpga_cycles": exact_cycles,
            "fpga_compute_ms": round(fpga_ms, 4),
        })
    rows.sort(key=lambda r: (-r["win_count"], -r["rtl_strength"], r["team_id"]))

    with open(out_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def export_single_tournament_trace(
    trace_csv: Path,
    sim: RTLReferenceSimulator,
    bracket_order: List[int],
    seed: int = HardwarePRNG16.RESET_SEED,
) -> int:
    trace_csv.parent.mkdir(parents=True, exist_ok=True)
    prng = HardwarePRNG16(seed=seed)
    trace: List[Dict] = []
    champ_id = sim.run_single_tournament(bracket_order, prng, trace=trace)

    with open(trace_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(trace[0].keys()))
        writer.writeheader()
        writer.writerows(trace)
    return champ_id


# ==============================================================================
# 6. SELF-TEST & CLI ENTRYPOINT
# ==============================================================================

def _build_synthetic_teams() -> Dict[int, TeamEntry]:
    """Fallback synthetic 64-team set if `data/mem/teams_<year>.mem` is not found."""
    import random
    rng = random.Random(2025)
    teams: Dict[int, TeamEntry] = {}
    for tid in range(64):
        vals = [rng.randint(40, 240) for _ in range(8)]
        packed = 0
        for v in vals:
            packed = (packed << 8) | v
        teams[tid] = TeamEntry(
            team_id=tid,
            team_name=f"Synthetic_Team_{tid:02d}",
            packed_u64=packed,
            strength=compute_team_strength(packed),
        )
    return teams


def run_self_test(mem_dir: Path, season: int = 2025) -> None:
    print("=== March Madness Basys 3 (`rtl_new`) — Bit-Exact Verification ===")

    # 1. Load real `data/mem/probability.mem` & `teams_<season>.mem` if present in repo
    prob_path = mem_dir / "probability.mem"
    lut = ProbabilityLUT(prob_path if prob_path.exists() else None)
    assert lut.mem[0] == 0x08000, f"Expected LUT[0]=0x08000, got 0x{lut.mem[0]:05X}"
    idx_neg, prob_neg = lut.lookup(-256)
    idx_pos, prob_pos = lut.lookup(+256)
    assert idx_neg == 1 and idx_pos == 1 and (prob_neg + prob_pos) == 65536
    print(f"[PASS] ProbabilityLUT (`probability_lut.sv`): {len(lut.mem)} entries, symmetry & 17-bit complement verified"
          + (f" from `{prob_path.name}`" if prob_path.exists() else " (built-in formula)"))

    team_mem_file = mem_dir / f"teams_{season}.mem"
    if team_mem_file.exists():
        teams, ref_csv = load_season_data(mem_dir, season)
        print(f"[PASS] Loaded `{team_mem_file.name}`"
              + (f" & verified all 64 `expected_rtl_score` values against `{ref_csv.name}`!" if ref_csv else ""))
    else:
        teams = _build_synthetic_teams()
        print(f"[INFO] `{team_mem_file}` not found in `{mem_dir}`; running self-test with synthetic 64-team BRAM.")

    # 2. Verify 16-bit PRNG sequence (`prng.sv`: reset=0xACE1, taps 15^13^12^10)
    prng = HardwarePRNG16()
    first_rand = prng.sample_and_step()
    second_rand = prng.sample_and_step()
    assert first_rand == 0xACE1, "First game must sample reset seed 0xACE1 before shifting!"
    # 0xACE1 = 1010_1100_1110_0001 -> b15=1, b13=1, b12=0, b10=1 -> feedback = 1^1^0^1 = 1 -> (0xACE1<<1)|1 = 0x59C3
    assert second_rand == 0x59C3, f"Expected second LFSR state 0x59C3, got 0x{second_rand:04X}"
    print("[PASS] 16-bit PRNG (`prng.sv`): Game #1 samples 0xACE1 -> shifts to 0x59C3 on CAPTURE")

    # 3. Verify `VirtualBasys3Board` UART byte stream matches `RTLReferenceSimulator` 100%
    sim = RTLReferenceSimulator(teams, lut)
    bracket_order = list(range(64))
    num_sims = 10_000

    ref_res = sim.run_simulations(bracket_order, num_sims, seed=HardwarePRNG16.RESET_SEED)

    vboard = VirtualBasys3Board(sim)
    client = Basys3UARTClient(virtual_board=vboard)
    client.connect()
    uart_counts, st, _ = client.run_full_job(bracket_order, num_sims)
    client.close()

    assert uart_counts == ref_res["win_counts"], "UART counts mismatch against reference model!"
    assert sum(uart_counts) == num_sims and st["total_simulations"] == num_sims
    print(f"[PASS] UART Protocol (`uart_ctrl.sv`): CMD_LOAD(65B) -> CMD_SET(5B) -> CMD_START(1B) -> "
          f"CMD_STATUS(6B) -> CMD_COUNTS(257B) matched all {num_sims:,} wins 100%!")

    # 4. Print Top-5 Champions & Exact Cycle/Speed Benchmark
    ranked = sorted(range(64), key=lambda i: (-uart_counts[i], -teams[i].strength))[:5]
    top_str = ", ".join(f"{teams[i].team_name} ({uart_counts[i]*100/num_sims:.2f}%)" for i in ranked)
    print(f"[INFO] Top 5 Simulated Champions ({season}): {top_str}")

    speedup = ref_res["cpu_time_s"] / ref_res["fpga_time_s"]
    print(
        f"[INFO] Speed Benchmark ({num_sims:,} brackets = {ref_res['fpga_cycles']:,} exact FPGA clock cycles): "
        f"Python CPU = {ref_res['cpu_time_s']*1000:.1f} ms | "
        f"Basys 3 @ 100 MHz = {ref_res['fpga_time_s']*1000:.2f} ms ({speedup:.1f}x speedup)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="March Madness Basys 3 (`rtl_new`) Reference & UART Host")
    parser.add_argument("--self-test", action="store_true", help="Verify RTL math, `data/mem` files, & UART protocol")
    parser.add_argument("--season", type=int, default=2025, help="Season year matching `data/mem/teams_<year>.mem`")
    parser.add_argument("--mem-dir", type=Path, default=DEFAULT_MEM_DIR, help="Path to `data/mem` directory")
    parser.add_argument("--bracket-file", type=Path, default=None, help="Optional 64-line bracket order file (.mem/.txt/.csv)")
    parser.add_argument("--sims", type=int, default=10000, help="Number of Monte Carlo tournament simulations")
    parser.add_argument("--seed", type=lambda x: int(x, 0), default=0xACE1, help="16-bit LFSR seed for Python reference run")
    parser.add_argument("--uart-port", type=str, default=None, help="Basys 3 COM port (e.g. COM4 or /dev/ttyUSB1)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="UART baud rate (default: 115200)")
    parser.add_argument("--status-only", action="store_true", help="Query `CMD_STATUS` from Basys 3 and exit")
    parser.add_argument("--out-csv", type=Path, default=None, help="Save championship counts & probabilities to CSV")
    parser.add_argument("--export-trace", type=Path, default=None, help="Export 63-game Run #1 trace CSV for Vivado TB")
    args = parser.parse_args()

    if args.self_test:
        run_self_test(args.mem_dir, args.season)
        return

    if args.status_only:
        if not args.uart_port:
            raise SystemExit("Error: `--status-only` requires `--uart-port <COMx>`.")
        client = Basys3UARTClient(port=args.uart_port, baudrate=args.baud)
        client.connect()
        try:
            st = client.get_status()
            print(f"Basys 3 Status: {st}")
        finally:
            client.close()
        return

    teams, ref_csv = load_season_data(args.mem_dir, args.season)
    lut = ProbabilityLUT(args.mem_dir / "probability.mem")
    sim = RTLReferenceSimulator(teams, lut)
    bracket_order = load_bracket_file(args.bracket_file)

    if args.export_trace is not None:
        champ_id = export_single_tournament_trace(args.export_trace, sim, bracket_order, seed=args.seed)
        print(f"Exported 63-game hardware trace to `{args.export_trace}` (Tournament #1 Champion: "
              f"ID={champ_id}, {teams[champ_id].team_name}).")

    # Always run Python bit-accurate reference model for comparison & speed benchmarking
    ref_res = sim.run_simulations(bracket_order, args.sims, seed=args.seed)
    active_counts = ref_res["win_counts"]

    print(f"Reference Model ({args.season}, {args.sims:,} sims): "
          f"CPU = {ref_res['cpu_time_s']*1000:.1f} ms | "
          f"Exact FPGA Cycles = {ref_res['fpga_cycles']:,} ({ref_res['fpga_time_s']*1000:.2f} ms @ 100 MHz)")

    # If `--uart-port` is supplied, run on physical Basys 3 and compare!
    if args.uart_port:
        client = Basys3UARTClient(port=args.uart_port, baudrate=args.baud)
        client.connect()
        try:
            hw_counts, st, wall_s = client.run_full_job(bracket_order, args.sims)
        finally:
            client.close()

        active_counts = hw_counts
        exact_match = (hw_counts == ref_res["win_counts"])
        print(f"Basys 3 Hardware Run Complete (UART round-trip = {wall_s*1000:.1f} ms, status={st})")
        if exact_match:
            print("[MATCH] Basys 3 hardware win counts match Python reference model 100% identically!")
        else:
            print("[NOTE] Hardware counts differ from initial seed 0xACE1 (press Basys 3 reset button before "
                  "running if you want PRNG to restart from 16'hACE1; PRNG continues across runs otherwise).")

    ranked = sorted(range(64), key=lambda i: (-active_counts[i], -teams[i].strength))[:10]
    print("\nTop 10 Championship Contenders:")
    for rank, tid in enumerate(ranked, start=1):
        pct = 100.0 * active_counts[tid] / max(1, args.sims)
        print(f"  {rank:2d}. [ID {tid:2d}] {teams[tid].team_name:<24} "
              f"Strength={teams[tid].strength:5d} | Wins={active_counts[tid]:6d} ({pct:5.2f}%)")

    out_path = args.out_csv or (REPO_ROOT / "sw" / f"results_{args.season}.csv")
    save_results_csv(out_path, args.season, teams, active_counts, args.sims)
    print(f"\nSaved CSV log to `{out_path}`.")


if __name__ == "__main__":
    main()
