"""
March Madness FPGA Predictor — Complete Python Software Suite
=============================================================
Target Hardware : Digilent Basys 3 (Artix-7 XC7A35T-1CPG236C, 100 MHz clock)
RTL Toolchain   : Vivado 2026.1
Modules Covered :
  1. M1 Shared Interface & Configurable Fixed-Point Formats (UQ8.8, Q9.8, UQ0.8 / UQ1.7)
  2. Floating-Point Reference Model (weighted stat differences + logistic win probability)
  3. Bit-Accurate Fixed-Point RTL Reference Model (`game_evaluator`, `probability_lut`,
     `prng` 32-bit Galois LFSR, `outcome_decider`, `bracket_controller`, `result_counters`)
  4. Basys 3 USB-UART Host Controller (`uart_rx + packet_parser` & `result_packetizer + uart_tx`
     binary packet builder, XOR checksum framing, loopback tester, and CSV output logger)
  5. Vivado Testbench Vector Exporter (`prob_lut.mem`, `team_stats.mem`, `initial_bracket.mem`,
     `config_weights.mem`, and cycle-accurate 63-game trace CSV)
  6. Historical Tournament Accuracy Evaluator & Laptop CPU vs. FPGA Speed Benchmarker
"""

import argparse
import csv
import math
import os
import random
import struct
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Optional pyserial import for live Basys 3 USB-UART communication
try:
    import serial
except ImportError:
    serial = None


# ==============================================================================
# 1. M1 SHARED INTERFACE & FIXED-POINT CONFIGURATION
# ==============================================================================

STAT_NAMES = [
    "seed_rank",     # 0: Tournament seed (1..16)
    "adj_off_eff",   # 1: Adjusted offensive efficiency (e.g., 80.0..140.0)
    "adj_def_eff",   # 2: Adjusted defensive efficiency (e.g., 80.0..140.0)
    "net_eff_diff",  # 3: Net efficiency differential (adj_off_eff - adj_def_eff)
    "eFG%",          # 4: Effective field goal percentage
    "TO%",           # 5: Turnover percentage
    "off_rebnd%",    # 6: Offensive rebound percentage
    "FTR",           # 7: Free throw rate
]


@dataclass
class M1Config:
    """
    Shared M1 Hardware/Software Interface Parameters.
    Supports switching percentage format between 'UQ0.8' (max ~0.996) and 'UQ1.7' (max ~1.992).
    """
    pct_format: str = "UQ0.8"       # 'UQ0.8' (scale=256) or 'UQ1.7' (scale=128)
    lut_addr_bits: int = 10         # 1024-entry Probability LUT (fits in 1x 18Kb BRAM)
    lut_max_score: float = 16.0     # Signed score range [-16.0, +16.0) mapped to LUT
    prob_frac_bits: int = 16        # UQ0.16 win probability threshold [0..65535]
    uart_baud: int = 115200         # Standard Basys 3 USB-UART baud rate
    fpga_clk_hz: int = 100_000_000  # Basys 3 100 MHz onboard clock


DEFAULT_WEIGHTS: Dict[str, float] = {
    "seed_rank":    -0.08,
    "adj_off_eff":   0.06,
    "adj_def_eff":  -0.06,
    "net_eff_diff":  0.08,
    "eFG%":          2.50,
    "TO%":          -2.00,
    "off_rebnd%":    1.25,
    "FTR":           0.75,
}


# ==============================================================================
# 2. BIT-ACCURATE FIXED-POINT HELPERS & HARDWARE ENCODING
# ==============================================================================

def clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


def to_twos_comp(val: int, bits: int) -> int:
    """Convert signed Python int to unsigned two's-complement bit pattern of width `bits`."""
    return val & ((1 << bits) - 1)


def from_twos_comp(bits_val: int, bits: int) -> int:
    """Sign-extend unsigned bit pattern of width `bits` to signed Python int."""
    mask = (1 << bits) - 1
    bits_val &= mask
    if bits_val & (1 << (bits - 1)):
        return bits_val - (1 << bits)
    return bits_val


@dataclass
class TeamRecord:
    team_id: int
    season: int
    team: str
    float_stats: Dict[str, float]
    fp_stats: Dict[str, int]


def normalize_percentage(val: float) -> float:
    """Accepts either ratio (0.524) or percentage (52.4) from CSV and returns ratio."""
    return val / 100.0 if val > 2.0 else val


def encode_team_fp(
    team_id: int,
    season: int,
    team: str,
    raw_stats: Dict[str, float],
    cfg: M1Config,
) -> TeamRecord:
    """
    Encodes raw CSV statistics into M1 fixed-point hardware formats:
      - seed_rank    : UQ5.0  (5-bit unsigned integer, 1..16)
      - adj_off_eff  : UQ8.8  (16-bit unsigned, scale = 256, e.g. 115.5 * 256 = 29568)
      - adj_def_eff  : UQ8.8  (16-bit unsigned, scale = 256, e.g. 98.25 * 256 = 25152)
      - net_eff_diff : Q9.8   (17-bit signed two's complement, scale = 256, e.g. 17.25 * 256 = 4416)
      - eFG%, TO%, off_rebnd%, FTR:
          * 'UQ0.8': 8-bit unsigned, 8 frac bits (scale = 256, max = 255/256 = 0.99609375)
          * 'UQ1.7': 8-bit unsigned, 7 frac bits (scale = 128, max = 255/128 = 1.9921875)
    """
    clean_float = {
        "seed_rank": float(raw_stats["seed_rank"]),
        "adj_off_eff": float(raw_stats["adj_off_eff"]),
        "adj_def_eff": float(raw_stats["adj_def_eff"]),
        "net_eff_diff": float(raw_stats["net_eff_diff"]),
        "eFG%": normalize_percentage(float(raw_stats["eFG%"])),
        "TO%": normalize_percentage(float(raw_stats["TO%"])),
        "off_rebnd%": normalize_percentage(float(raw_stats["off_rebnd%"])),
        "FTR": normalize_percentage(float(raw_stats["FTR"])),
    }

    pct_scale = 256 if cfg.pct_format == "UQ0.8" else 128

    fp = {
        "seed_rank": clamp(int(round(clean_float["seed_rank"])), 1, 16),
        "adj_off_eff": clamp(int(round(clean_float["adj_off_eff"] * 256)), 0, 65535),
        "adj_def_eff": clamp(int(round(clean_float["adj_def_eff"] * 256)), 0, 65535),
        "net_eff_diff": clamp(int(round(clean_float["net_eff_diff"] * 256)), -65536, 65535),
        "eFG%": clamp(int(round(clean_float["eFG%"] * pct_scale)), 0, 255),
        "TO%": clamp(int(round(clean_float["TO%"] * pct_scale)), 0, 255),
        "off_rebnd%": clamp(int(round(clean_float["off_rebnd%"] * pct_scale)), 0, 255),
        "FTR": clamp(int(round(clean_float["FTR"] * pct_scale)), 0, 255),
    }
    return TeamRecord(team_id=team_id, season=season, team=team, float_stats=clean_float, fp_stats=fp)


def encode_weights_fp(weights: Dict[str, float]) -> Dict[str, int]:
    """Encodes metric weights as signed 16-bit Q8.8 integers [-32768, +32767]."""
    return {k: clamp(int(round(weights[k] * 256)), -32768, 32767) for k in STAT_NAMES}


def pack_team_bram_word(rec: TeamRecord) -> int:
    """
    Packs all 8 encoded statistics of a single team into a byte-aligned 96-bit (12-byte)
    word for `team_stats_mem` BRAM and UART `LOAD_TEAM` packets:
      [95:88] seed_rank    (8-bit zero-extended from 5-bit UQ5.0)
      [87:72] adj_off_eff  (16-bit UQ8.8)
      [71:56] adj_def_eff  (16-bit UQ8.8)
      [55:32] net_eff_diff (24-bit sign-extended from 17-bit Q9.8 two's complement)
      [31:24] eFG%         (8-bit UQ0.8 or UQ1.7)
      [23:16] TO%          (8-bit UQ0.8 or UQ1.7)
      [15:8]  off_rebnd%   (8-bit UQ0.8 or UQ1.7)
      [7:0]   FTR          (8-bit UQ0.8 or UQ1.7)
    """
    fp = rec.fp_stats
    net_u24 = to_twos_comp(fp["net_eff_diff"], 24)
    return (
        ((fp["seed_rank"] & 0xFF) << 88)
        | ((fp["adj_off_eff"] & 0xFFFF) << 72)
        | ((fp["adj_def_eff"] & 0xFFFF) << 56)
        | ((net_u24 & 0xFFFFFF) << 32)
        | ((fp["eFG%"] & 0xFF) << 24)
        | ((fp["TO%"] & 0xFF) << 16)
        | ((fp["off_rebnd%"] & 0xFF) << 8)
        | (fp["FTR"] & 0xFF)
    )


# ==============================================================================
# 3. RTL MODULE EQUIVALENTS (PRNG, PROBABILITY LUT, GAME EVALUATOR, BRACKET)
# ==============================================================================

class HardwareLFSR32:
    """
    Deterministic 32-bit Galois LFSR matching RTL `prng` module.
    Polynomial: x^32 + x^22 + x^2 + x^1 + 1 (0x80200003, maximal period 2^32 - 1).
    Advances once per game; upper 16 bits supply UQ0.16 random value to `outcome_decider`.
    """
    POLY_MASK = 0x80200003

    def __init__(self, seed: int = 0xACE1BEEF):
        self.state = (seed & 0xFFFFFFFF) or 0x00000001

    def step(self) -> int:
        lsb = self.state & 1
        self.state >>= 1
        if lsb:
            self.state ^= self.POLY_MASK
        return (self.state >> 16) & 0xFFFF


class ProbabilityLUT:
    """
    Bit-accurate ROM model for RTL `probability_lut` module.
    Maps signed Q16.16 weighted score to 16-bit UQ0.16 win probability threshold:
      threshold = round(65535 / (1 + exp(-score)))
    """
    def __init__(self, cfg: M1Config):
        self.cfg = cfg
        self.size = 1 << cfg.lut_addr_bits        # 1024 entries
        self.max_val = (1 << cfg.prob_frac_bits) - 1  # 65535
        self.step_size = (2.0 * cfg.lut_max_score) / self.size  # 0.03125 (2^-5)
        self.table: List[int] = [
            clamp(
                int(round(self.max_val / (1.0 + math.exp(-(-cfg.lut_max_score + (i + 0.5) * self.step_size))))),
                0,
                self.max_val,
            )
            for i in range(self.size)
        ]

    def score_q16_to_index(self, score_q16: int) -> int:
        """
        Hardware bit-slice LUT indexing from signed Q16.16 score:
        Clamps score to [-16.0, +15.96875], arithmetic right-shifts by 11 bits (step = 2^-5),
        and adds 512 midpoint offset.
        """
        min_q16 = int(-self.cfg.lut_max_score * 65536)
        max_q16 = int(self.cfg.lut_max_score * 65536) - (1 << 11)
        clamped = clamp(score_q16, min_q16, max_q16)
        idx = (clamped >> 11) + (self.size >> 1)
        return clamp(idx, 0, self.size - 1)


class MarchMadnessModel:
    """
    Dual Floating-Point Reference & Bit-Accurate Fixed-Point Hardware Simulator.
    """
    def __init__(self, cfg: Optional[M1Config] = None, weights: Optional[Dict[str, float]] = None):
        self.cfg = cfg or M1Config()
        self.float_weights = dict(weights or DEFAULT_WEIGHTS)
        self.fp_weights = encode_weights_fp(self.float_weights)
        self.lut = ProbabilityLUT(self.cfg)

    def evaluate_game_float(self, team_a: TeamRecord, team_b: TeamRecord) -> Tuple[float, float]:
        """Floating-point weighted difference & logistic win probability for Team A."""
        score = sum(
            self.float_weights[s] * (team_a.float_stats[s] - team_b.float_stats[s])
            for s in STAT_NAMES
        )
        prob_a = 1.0 / (1.0 + math.exp(-score))
        return score, prob_a

    def evaluate_game_fp(self, team_a: TeamRecord, team_b: TeamRecord) -> Tuple[int, int, int]:
        """
        Bit-accurate model of RTL `game_evaluator` + `probability_lut`:
          1. Zero-extends unsigned 16-bit efficiencies (`adj_off_eff`, `adj_def_eff`) to
             signed 17-bit values before subtraction so negative differences are exact (Page 8).
          2. Aligns all 8 signed differences to Q10.8 (8 fractional bits).
          3. Multiplies each Q10.8 difference by its signed 16-bit Q8.8 weight (Basys 3 DSP48E1)
             producing Q18.16 products, summed into a signed accumulator.
          4. Indexes `probability_lut` to output a 16-bit UQ0.16 win threshold.
        """
        a = team_a.fp_stats
        b = team_b.fp_stats
        pct_shift = 0 if self.cfg.pct_format == "UQ0.8" else 1

        diffs_q8 = {
            "seed_rank":    (int(a["seed_rank"]) - int(b["seed_rank"])) << 8,
            "adj_off_eff":  int(a["adj_off_eff"]) - int(b["adj_off_eff"]),
            "adj_def_eff":  int(a["adj_def_eff"]) - int(b["adj_def_eff"]),
            "net_eff_diff": int(a["net_eff_diff"]) - int(b["net_eff_diff"]),
            "eFG%":         (int(a["eFG%"]) - int(b["eFG%"])) << pct_shift,
            "TO%":          (int(a["TO%"]) - int(b["TO%"])) << pct_shift,
            "off_rebnd%":   (int(a["off_rebnd%"]) - int(b["off_rebnd%"])) << pct_shift,
            "FTR":          (int(a["FTR"]) - int(b["FTR"])) << pct_shift,
        }

        acc_q16 = 0
        for stat in STAT_NAMES:
            acc_q16 += diffs_q8[stat] * self.fp_weights[stat]

        acc_q16 = clamp(acc_q16, -(1 << 31), (1 << 31) - 1)
        lut_idx = self.lut.score_q16_to_index(acc_q16)
        threshold = self.lut.table[lut_idx]
        return acc_q16, lut_idx, threshold

    def simulate_single_bracket_fp(
        self,
        teams_by_id: Dict[int, TeamRecord],
        initial_bracket_ids: List[int],
        prng: HardwareLFSR32,
        trace_games: Optional[List[Dict]] = None,
    ) -> int:
        """Sequential single-lane tournament simulation matching `bracket_controller`."""
        current_round = list(initial_bracket_ids)
        round_num = 1
        while len(current_round) > 1:
            next_round = []
            for i in range(0, len(current_round), 2):
                id_a, id_b = current_round[i], current_round[i + 1]
                acc_q16, lut_idx, thresh = self.evaluate_game_fp(teams_by_id[id_a], teams_by_id[id_b])
                rand_u16 = prng.step()
                winner_id = id_a if rand_u16 < thresh else id_b
                next_round.append(winner_id)

                if trace_games is not None:
                    trace_games.append({
                        "round": round_num,
                        "team_a_id": id_a,
                        "team_b_id": id_b,
                        "acc_q16": acc_q16,
                        "lut_idx": lut_idx,
                        "thresh_u16": thresh,
                        "rand_u16": rand_u16,
                        "winner_id": winner_id,
                    })
            current_round = next_round
            round_num += 1
        return current_round[0]

    def run_monte_carlo_fp(
        self,
        teams_by_id: Dict[int, TeamRecord],
        initial_bracket_ids: List[int],
        num_sims: int = 1000,
        seed: int = 0xACE1BEEF,
    ) -> Dict:
        """Bit-accurate Monte Carlo simulation matching `main_controller` + `result_counters`."""
        prng = HardwareLFSR32(seed=seed)
        champ_counts = {tid: 0 for tid in initial_bracket_ids}

        t0 = time.perf_counter()
        for _ in range(num_sims):
            champ_id = self.simulate_single_bracket_fp(teams_by_id, initial_bracket_ids, prng)
            champ_counts[champ_id] += 1
        elapsed_s = time.perf_counter() - t0

        games_per_sim = len(initial_bracket_ids) - 1
        est_cycles_per_game = 6  # Sequential single-lane pipeline estimate
        est_fpga_cycles = num_sims * games_per_sim * est_cycles_per_game
        est_fpga_time_s = est_fpga_cycles / self.cfg.fpga_clk_hz

        return {
            "champ_counts": champ_counts,
            "completed_runs": num_sims,
            "cpu_time_s": elapsed_s,
            "est_fpga_cycles": est_fpga_cycles,
            "est_fpga_time_s": est_fpga_time_s,
            "final_lfsr_state": prng.state,
        }

    def run_monte_carlo_float(
        self,
        teams_by_id: Dict[int, TeamRecord],
        initial_bracket_ids: List[int],
        num_sims: int = 1000,
        seed: int = 42,
    ) -> Dict:
        """Floating-point Monte Carlo simulation for baseline accuracy comparison."""
        rng = random.Random(seed)
        champ_counts = {tid: 0 for tid in initial_bracket_ids}

        t0 = time.perf_counter()
        for _ in range(num_sims):
            current_round = list(initial_bracket_ids)
            while len(current_round) > 1:
                next_round = []
                for i in range(0, len(current_round), 2):
                    id_a, id_b = current_round[i], current_round[i + 1]
                    _, prob_a = self.evaluate_game_float(teams_by_id[id_a], teams_by_id[id_b])
                    next_round.append(id_a if rng.random() < prob_a else id_b)
                current_round = next_round
            champ_counts[current_round[0]] += 1
        elapsed_s = time.perf_counter() - t0

        return {
            "champ_counts": champ_counts,
            "completed_runs": num_sims,
            "cpu_time_s": elapsed_s,
        }


# ==============================================================================
# 4. UART PACKETIZER, RESULT PARSER, AND BASYS 3 HOST INTERFACE
# ==============================================================================
# Framing (Big-Endian):
#   [SOF=0xAA] [PKT_TYPE (1B)] [PAYLOAD_LEN (2B)] [PAYLOAD...] [XOR_CSUM (1B)] [EOF=0x55]

SOF_BYTE = 0xAA
EOF_BYTE = 0x55

PKT_LOAD_CONFIG    = 0x01  # 8x int16 weights + uint32 sim_count + uint32 seed (24 B)
PKT_LOAD_TEAM      = 0x02  # uint8 team_id + 12B packed 96-bit fixed-point stats (13 B)
PKT_LOAD_BRACKET   = 0x03  # 64x uint8 initial bracket team IDs (64 B)
PKT_START_RUN      = 0x04  # Trigger simulation state machine (0 B)
PKT_LOOPBACK_PING  = 0x05  # M4 board UART loopback verification ping
PKT_RESULT_SUMMARY = 0x81  # uint32 runs + uint64 cycles + 64x (uint8 id, uint32 wins) (332 B)
PKT_LOOPBACK_ACK   = 0x85  # M4 board UART loopback echo response


def compute_xor_checksum(pkt_type: int, payload: bytes) -> int:
    plen = len(payload)
    csum = pkt_type ^ ((plen >> 8) & 0xFF) ^ (plen & 0xFF)
    for b in payload:
        csum ^= b
    return csum & 0xFF


def build_uart_frame(pkt_type: int, payload: bytes = b"") -> bytes:
    header = struct.pack(">BH", pkt_type, len(payload))
    csum = compute_xor_checksum(pkt_type, payload)
    return bytes([SOF_BYTE]) + header + payload + bytes([csum, EOF_BYTE])


def parse_uart_frame(frame: bytes) -> Tuple[int, bytes]:
    if len(frame) < 6 or frame[0] != SOF_BYTE or frame[-1] != EOF_BYTE:
        raise ValueError("Invalid UART frame delimiters (SOF/EOF mismatch).")
    pkt_type, plen = struct.unpack(">BH", frame[1:4])
    if len(frame) != plen + 6:
        raise ValueError(f"Frame length mismatch: expected {plen + 6}, got {len(frame)}.")
    payload = frame[4:4 + plen]
    expected_csum = compute_xor_checksum(pkt_type, payload)
    if frame[-2] != expected_csum:
        raise ValueError(f"UART checksum error: expected 0x{expected_csum:02X}, got 0x{frame[-2]:02X}.")
    return pkt_type, payload


def make_config_packet(fp_weights: Dict[str, int], sim_count: int, seed: int) -> bytes:
    w_packed = b"".join(struct.pack(">h", fp_weights[s]) for s in STAT_NAMES)
    payload = w_packed + struct.pack(">II", sim_count, seed & 0xFFFFFFFF)
    return build_uart_frame(PKT_LOAD_CONFIG, payload)


def make_team_packet(rec: TeamRecord) -> bytes:
    word96 = pack_team_bram_word(rec)
    payload = struct.pack(">B", rec.team_id) + word96.to_bytes(12, byteorder="big")
    return build_uart_frame(PKT_LOAD_TEAM, payload)


def make_bracket_packet(initial_bracket_ids: List[int]) -> bytes:
    return build_uart_frame(PKT_LOAD_BRACKET, bytes(tid & 0xFF for tid in initial_bracket_ids))


def make_start_packet() -> bytes:
    return build_uart_frame(PKT_START_RUN, b"")


def encode_fpga_result_packet(
    completed_runs: int,
    compute_cycles: int,
    champ_counts: Dict[int, int],
) -> bytes:
    payload = bytearray(struct.pack(">IQ", completed_runs, compute_cycles))
    for tid in sorted(champ_counts.keys()):
        payload += struct.pack(">BI", tid & 0xFF, champ_counts[tid])
    return build_uart_frame(PKT_RESULT_SUMMARY, bytes(payload))


def decode_fpga_result_packet(frame: bytes) -> Dict:
    pkt_type, payload = parse_uart_frame(frame)
    if pkt_type != PKT_RESULT_SUMMARY:
        raise ValueError(f"Unexpected packet type 0x{pkt_type:02X} (expected 0x81).")
    completed_runs, compute_cycles = struct.unpack(">IQ", payload[:12])
    champ_counts = {}
    offset = 12
    while offset + 5 <= len(payload):
        tid, wins = struct.unpack(">BI", payload[offset:offset + 5])
        champ_counts[tid] = wins
        offset += 5
    return {
        "completed_runs": completed_runs,
        "compute_cycles": compute_cycles,
        "champ_counts": champ_counts,
    }


class Basys3HostInterface:
    """Manages USB-UART communication with the Digilent Basys 3 board."""
    def __init__(self, port: Optional[str] = None, baudrate: int = 115200, timeout: float = 10.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    def connect(self):
        if self.port is None:
            return
        if serial is None:
            raise RuntimeError("pyserial is required for hardware UART (`pip install pyserial`).")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def run_loopback_test(self, test_bytes: bytes = b"BASYS3_M4_OK") -> bool:
        """M4 Pre-Break Checkpoint: Verifies board USB-UART RX/TX framing integrity."""
        tx_frame = build_uart_frame(PKT_LOOPBACK_PING, test_bytes)
        if not (self.ser and self.ser.is_open):
            # Offline virtual loopback check
            mock_rx = build_uart_frame(PKT_LOOPBACK_ACK, test_bytes)
            rx_type, rx_payload = parse_uart_frame(mock_rx)
            return rx_type == PKT_LOOPBACK_ACK and rx_payload == test_bytes

        self.ser.write(tx_frame)
        self.ser.flush()
        rx_frame = self.receive_frame()
        rx_type, rx_payload = parse_uart_frame(rx_frame)
        return rx_type == PKT_LOOPBACK_ACK and rx_payload == test_bytes

    def transmit_tournament_job(
        self,
        model: MarchMadnessModel,
        teams_by_id: Dict[int, TeamRecord],
        initial_bracket_ids: List[int],
        num_sims: int,
        seed: int,
    ) -> List[bytes]:
        frames = [make_config_packet(model.fp_weights, num_sims, seed)]
        for tid in sorted(teams_by_id.keys()):
            frames.append(make_team_packet(teams_by_id[tid]))
        frames.append(make_bracket_packet(initial_bracket_ids))
        frames.append(make_start_packet())

        if self.ser and self.ser.is_open:
            for f in frames:
                self.ser.write(f)
            self.ser.flush()
        return frames

    def receive_frame(self) -> bytes:
        if not (self.ser and self.ser.is_open):
            raise RuntimeError("Serial port is not open.")
        while True:
            b = self.ser.read(1)
            if not b:
                raise TimeoutError("Timed out waiting for Basys 3 UART SOF (0xAA).")
            if b[0] == SOF_BYTE:
                break
        hdr = self.ser.read(3)
        _, plen = struct.unpack(">BH", hdr)
        rest = self.ser.read(plen + 2)
        return bytes([SOF_BYTE]) + hdr + rest


# ==============================================================================
# 5. CSV DATA PIPELINE, HISTORICAL ACCURACY, & VIVADO TESTBENCH EXPORTER
# ==============================================================================

def load_teams_csv(csv_path: str, season: int, cfg: M1Config) -> Tuple[Dict[int, TeamRecord], Dict[str, int]]:
    teams_by_id: Dict[int, TeamRecord] = {}
    name_to_id: Dict[str, int] = {}
    next_id = 0

    with open(csv_path, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["season"]) != season:
                continue
            raw_stats = {stat: float(row[stat]) for stat in STAT_NAMES}
            rec = encode_team_fp(next_id, season, row["team"].strip(), raw_stats, cfg)
            teams_by_id[next_id] = rec
            name_to_id[rec.team] = next_id
            next_id += 1
    return teams_by_id, name_to_id


def save_results_csv(
    output_csv_path: str,
    season: int,
    teams_by_id: Dict[int, TeamRecord],
    completed_runs: int,
    compute_cycles: int,
    champ_counts: Dict[int, int],
    fpga_clk_hz: int = 100_000_000,
):
    fpga_time_ms = (compute_cycles / fpga_clk_hz) * 1000.0
    rows = []
    for tid, wins in champ_counts.items():
        rec = teams_by_id[tid]
        rows.append({
            "season": season,
            "team_id": tid,
            "team": rec.team,
            "seed_rank": int(rec.float_stats["seed_rank"]),
            "championship_count": wins,
            "win_probability": round(wins / max(1, completed_runs), 6),
            "completed_runs": completed_runs,
            "compute_cycles": compute_cycles,
            "fpga_compute_time_ms": round(fpga_time_ms, 4),
        })
    rows.sort(key=lambda r: (-r["championship_count"], r["seed_rank"], r["team"]))

    fieldnames = [
        "season", "team_id", "team", "seed_rank",
        "championship_count", "win_probability",
        "completed_runs", "compute_cycles", "fpga_compute_time_ms",
    ]
    with open(output_csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def evaluate_historical_results(
    results_csv_path: str,
    season: int,
    model: MarchMadnessModel,
    teams_by_id: Dict[int, TeamRecord],
    name_to_id: Dict[str, int],
    mc_champ_counts: Dict[int, int],
    completed_runs: int,
) -> Dict:
    total_games = 0
    correct_float = 0
    correct_fp = 0
    fp_float_agree = 0
    actual_champion = None
    max_round = -1

    with open(results_csv_path, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["season"]) != season:
                continue
            rnd = int(row["round"])
            ta = teams_by_id[name_to_id[row["team_a"].strip()]]
            tb = teams_by_id[name_to_id[row["team_b"].strip()]]
            actual_win_name = row["winner"].strip()

            _, prob_a_flt = model.evaluate_game_float(ta, tb)
            pred_flt = ta.team if prob_a_flt >= 0.5 else tb.team

            _, _, thresh_u16 = model.evaluate_game_fp(ta, tb)
            pred_fp = ta.team if thresh_u16 >= 32768 else tb.team

            total_games += 1
            if pred_flt == actual_win_name:
                correct_float += 1
            if pred_fp == actual_win_name:
                correct_fp += 1
            if pred_flt == pred_fp:
                fp_float_agree += 1

            if rnd >= max_round:
                max_round = rnd
                actual_champion = actual_win_name

    champ_hit_rate = 0.0
    if actual_champion and actual_champion in name_to_id:
        cid = name_to_id[actual_champion]
        champ_hit_rate = mc_champ_counts.get(cid, 0) / max(1, completed_runs)

    return {
        "total_games": total_games,
        "correct_games_float": correct_float,
        "correct_games_fp": correct_fp,
        "accuracy_fp_pct": 100.0 * correct_fp / max(1, total_games),
        "fp_vs_float_agreement_pct": 100.0 * fp_float_agree / max(1, total_games),
        "actual_champion": actual_champion,
        "champion_hit_rate": champ_hit_rate,
    }


def export_vivado_test_vectors(
    out_dir: str,
    model: MarchMadnessModel,
    teams_by_id: Dict[int, TeamRecord],
    initial_bracket_ids: List[int],
    seed: int = 0xACE1BEEF,
) -> Tuple[int, List[Dict]]:
    """
    Generates `.mem` BRAM/ROM files (for Verilog `$readmemh`) and cycle-accurate
    game evaluation vectors for Vivado 2026.1 module & top-level testbenches.
    """
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "prob_lut.mem"), "w") as f:
        for val in model.lut.table:
            f.write(f"{val:04X}\n")

    with open(os.path.join(out_dir, "team_stats.mem"), "w") as f:
        for tid in sorted(teams_by_id.keys()):
            f.write(f"{pack_team_bram_word(teams_by_id[tid]):024X}\n")

    with open(os.path.join(out_dir, "initial_bracket.mem"), "w") as f:
        for tid in initial_bracket_ids:
            f.write(f"{tid & 0xFF:02X}\n")

    with open(os.path.join(out_dir, "config_weights.mem"), "w") as f:
        for stat in STAT_NAMES:
            f.write(f"{to_twos_comp(model.fp_weights[stat], 16):04X}\n")

    prng = HardwareLFSR32(seed=seed)
    trace: List[Dict] = []
    champ_id = model.simulate_single_bracket_fp(teams_by_id, initial_bracket_ids, prng, trace_games=trace)

    vec_path = os.path.join(out_dir, "tb_single_bracket_vec.csv")
    with open(vec_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "game_idx", "round", "team_a_id", "team_b_id",
            "acc_q16_signed", "acc_q16_hex", "lut_idx",
            "thresh_u16_hex", "rand_u16_hex", "winner_id",
        ])
        writer.writeheader()
        for idx, g in enumerate(trace):
            writer.writerow({
                "game_idx": idx,
                "round": g["round"],
                "team_a_id": g["team_a_id"],
                "team_b_id": g["team_b_id"],
                "acc_q16_signed": g["acc_q16"],
                "acc_q16_hex": f"{to_twos_comp(g['acc_q16'], 32):08X}",
                "lut_idx": g["lut_idx"],
                "thresh_u16_hex": f"{g['thresh_u16']:04X}",
                "rand_u16_hex": f"{g['rand_u16']:04X}",
                "winner_id": g["winner_id"],
            })
    return champ_id, trace


# ==============================================================================
# 6. DEMO DATASET GENERATOR, CLI ENTRYPOINT, & SELF-TEST
# ==============================================================================

def generate_demo_tournament_csvs(teams_csv: str, results_csv: str, season: int = 2025):
    rng = random.Random(2025)
    regions = ["East", "West", "South", "Midwest"]
    bracket_seed_order = [1, 16, 8, 9, 5, 12, 4, 13, 6, 11, 3, 14, 7, 10, 2, 15]

    team_rows = []
    for reg in regions:
        for s in bracket_seed_order:
            adj_off = round(124.5 - s * 1.35 + rng.uniform(-2.5, 2.5), 2)
            adj_def = round(91.0 + s * 1.15 + rng.uniform(-2.5, 2.5), 2)
            net_eff = round(adj_off - adj_def, 2)
            efg = round(0.565 - s * 0.004 + rng.uniform(-0.015, 0.015), 4)
            to_pct = round(0.150 + s * 0.0025 + rng.uniform(-0.012, 0.012), 4)
            orb_pct = round(0.345 - s * 0.0035 + rng.uniform(-0.02, 0.02), 4)
            ftr = round(0.365 - s * 0.003 + rng.uniform(-0.025, 0.025), 4)
            team_rows.append({
                "season": season,
                "team": f"{reg}_Seed{s}",
                "seed_rank": s,
                "adj_off_eff": adj_off,
                "adj_def_eff": adj_def,
                "net_eff_diff": net_eff,
                "eFG%": efg,
                "TO%": to_pct,
                "off_rebnd%": orb_pct,
                "FTR": ftr,
            })

    with open(teams_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["season", "team"] + STAT_NAMES)
        writer.writeheader()
        writer.writerows(team_rows)

    cfg = M1Config()
    model = MarchMadnessModel(cfg)
    teams_by_id, _ = load_teams_csv(teams_csv, season, cfg)
    curr_ids = list(range(64))
    hist_rows = []
    rnd = 1
    while len(curr_ids) > 1:
        nxt = []
        for i in range(0, len(curr_ids), 2):
            ta, tb = teams_by_id[curr_ids[i]], teams_by_id[curr_ids[i + 1]]
            _, p_a = model.evaluate_game_float(ta, tb)
            win = ta if rng.random() < p_a else tb
            nxt.append(win.team_id)
            hist_rows.append({
                "season": season,
                "round": rnd,
                "team_a": ta.team,
                "team_b": tb.team,
                "winner": win.team,
            })
        curr_ids = nxt
        rnd += 1

    with open(results_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["season", "round", "team_a", "team_b", "winner"])
        writer.writeheader()
        writer.writerows(hist_rows)


def run_self_test():
    print("=== March Madness FPGA Predictor — Software Suite Verification ===")
    cfg = M1Config(pct_format="UQ0.8")

    # 1. Verify Page 8 Fixed-Point Format Examples
    sample = encode_team_fp(
        0, 2026, "Page8_Check",
        {
            "seed_rank": 1, "adj_off_eff": 115.5, "adj_def_eff": 98.25,
            "net_eff_diff": 17.25, "eFG%": 0.55, "TO%": 0.16, "off_rebnd%": 0.32, "FTR": 0.35,
        },
        cfg,
    )
    assert sample.fp_stats["adj_off_eff"] == 29568
    assert sample.fp_stats["adj_def_eff"] == 25152
    assert sample.fp_stats["net_eff_diff"] == 4416
    print("[PASS] Page 8 Fixed-Point Encoding Check: 115.5->29568, 98.25->25152, 17.25->4416")

    # 2. Build Demo Tournament Dataset
    os.makedirs("demo_artifacts", exist_ok=True)
    teams_csv = "demo_artifacts/teams_demo.csv"
    hist_csv = "demo_artifacts/historical_results_demo.csv"
    out_log_csv = "demo_artifacts/fpga_simulation_results.csv"
    generate_demo_tournament_csvs(teams_csv, hist_csv, season=2025)

    teams_by_id, name_to_id = load_teams_csv(teams_csv, 2025, cfg)
    bracket_ids = list(range(64))
    model = MarchMadnessModel(cfg)

    # 3. Quantization Error Check (Float vs Fixed-Point LUT)
    max_prob_err = 0.0
    for i in range(0, 64, 2):
        _, p_flt = model.evaluate_game_float(teams_by_id[i], teams_by_id[i + 1])
        _, _, thresh_u16 = model.evaluate_game_fp(teams_by_id[i], teams_by_id[i + 1])
        max_prob_err = max(max_prob_err, abs(p_flt - (thresh_u16 / 65535.0)))
    print(f"[PASS] Round-of-64 Float vs Fixed-Point Max Win-Prob Error: {max_prob_err:.5f}")

    # 4. Run 10,000 Monte Carlo Simulations & UART Packetizer/Parser Verification
    num_sims = 10_000
    seed = 0xACE1BEEF
    fp_res = model.run_monte_carlo_fp(teams_by_id, bracket_ids, num_sims=num_sims, seed=seed)

    host = Basys3HostInterface(port=None)
    assert host.run_loopback_test(), "Virtual UART loopback failed!"
    tx_frames = host.transmit_tournament_job(model, teams_by_id, bracket_ids, num_sims, seed)
    total_tx_bytes = sum(len(f) for f in tx_frames)
    mock_rx_frame = encode_fpga_result_packet(
        fp_res["completed_runs"], fp_res["est_fpga_cycles"], fp_res["champ_counts"]
    )
    decoded_rx = decode_fpga_result_packet(mock_rx_frame)
    assert decoded_rx["champ_counts"] == fp_res["champ_counts"]
    print(f"[PASS] UART Framing & Checksum Loopback: TX={len(tx_frames)} pkts ({total_tx_bytes} B), RX={len(mock_rx_frame)} B")

    # 5. Export Output Log CSV & Vivado Testbench Vectors
    save_results_csv(
        out_log_csv, 2025, teams_by_id,
        decoded_rx["completed_runs"], decoded_rx["compute_cycles"], decoded_rx["champ_counts"]
    )
    champ_run1, _ = export_vivado_test_vectors("demo_artifacts/vivado_vectors", model, teams_by_id, bracket_ids, seed)
    print(f"[PASS] Vivado RTL Vectors Exported: prob_lut.mem, team_stats.mem, tb_single_bracket_vec.csv (Run#1 Champ ID={champ_run1})")

    # 6. Historical Accuracy & Speed Benchmark Summary
    acc = evaluate_historical_results(
        hist_csv, 2025, model, teams_by_id, name_to_id, fp_res["champ_counts"], num_sims
    )
    speedup = fp_res["cpu_time_s"] / fp_res["est_fpga_time_s"]
    print(
        f"[INFO] Historical Eval: {acc['correct_games_fp']}/{acc['total_games']} games ({acc['accuracy_fp_pct']:.1f}%), "
        f"FP/Float Agreement: {acc['fp_vs_float_agreement_pct']:.1f}%, "
        f"Champ Hit Rate ({acc['actual_champion']}): {acc['champion_hit_rate']*100:.2f}%"
    )
    print(
        f"[INFO] Speed Benchmark ({num_sims:,} brackets / {num_sims*63:,} games): "
        f"Python CPU = {fp_res['cpu_time_s']*1000:.1f} ms | "
        f"Basys 3 @ 100 MHz (1-lane est.) = {fp_res['est_fpga_time_s']*1000:.2f} ms ({speedup:.1f}x speedup)"
    )


def main():
    parser = argparse.ArgumentParser(description="March Madness FPGA Predictor Host & Reference Suite")
    parser.add_argument("--self-test", action="store_true", help="Run built-in verification & demo suite")
    parser.add_argument("--teams-csv", type=str, help="Path to team-statistics CSV")
    parser.add_argument("--results-csv", type=str, default=None, help="Optional historical results CSV for accuracy")
    parser.add_argument("--season", type=int, default=2025, help="Tournament season year")
    parser.add_argument("--sims", type=int, default=10000, help="Number of Monte Carlo bracket simulations")
    parser.add_argument("--seed", type=lambda x: int(x, 0), default=0xACE1BEEF, help="32-bit PRNG seed (hex or int)")
    parser.add_argument("--pct-format", choices=["UQ0.8", "UQ1.7"], default="UQ0.8", help="8-bit percentage format")
    parser.add_argument("--uart-port", type=str, default=None, help="Serial port for Basys 3 (e.g. COM4 or /dev/ttyUSB1)")
    parser.add_argument("--baud", type=int, default=115200, help="UART baud rate")
    parser.add_argument("--export-vectors", type=str, default="vivado_vectors", help="Directory for Vivado .mem & TB vectors")
    parser.add_argument("--out-csv", type=str, default="fpga_results_log.csv", help="Output CSV log path")
    args = parser.parse_args()

    if args.self_test or not args.teams_csv:
        run_self_test()
        return

    cfg = M1Config(pct_format=args.pct_format, uart_baud=args.baud)
    model = MarchMadnessModel(cfg)
    teams_by_id, name_to_id = load_teams_csv(args.teams_csv, args.season, cfg)
    bracket_ids = sorted(teams_by_id.keys())

    export_vivado_test_vectors(args.export_vectors, model, teams_by_id, bracket_ids, args.seed)
    print(f"Exported Vivado test vectors to `{args.export_vectors}/`.")

    if args.uart_port:
        host = Basys3HostInterface(port=args.uart_port, baudrate=args.baud)
        host.connect()
        try:
            host.transmit_tournament_job(model, teams_by_id, bracket_ids, args.sims, args.seed)
            rx_frame = host.receive_frame()
            hw_res = decode_fpga_result_packet(rx_frame)
        finally:
            host.close()
        champ_counts = hw_res["champ_counts"]
        cycles = hw_res["compute_cycles"]
        runs = hw_res["completed_runs"]
    else:
        fp_res = model.run_monte_carlo_fp(teams_by_id, bracket_ids, num_sims=args.sims, seed=args.seed)
        champ_counts = fp_res["champ_counts"]
        cycles = fp_res["est_fpga_cycles"]
        runs = fp_res["completed_runs"]

    save_results_csv(args.out_csv, args.season, teams_by_id, runs, cycles, champ_counts, cfg.fpga_clk_hz)
    print(f"Saved simulation results log to `{args.out_csv}`.")

    if args.results_csv:
        acc = evaluate_historical_results(
            args.results_csv, args.season, model, teams_by_id, name_to_id, champ_counts, runs
        )
        print(f"Historical Accuracy: {acc['correct_games_fp']}/{acc['total_games']} ({acc['accuracy_fp_pct']:.2f}%), "
              f"Champion Hit Rate ({acc['actual_champion']}): {acc['champion_hit_rate']*100:.2f}%")


if __name__ == "__main__":
    main()
