"""SMPTE LTC (biphase-mark) encode/decode. Probe uses the decoder; please reuse it."""

from __future__ import annotations

from dataclasses import dataclass

from .timecode import Timecode, add_frames, to_framecount

SYNC = "0011111111111101"  # bits 64-79, transmitted in this order (bit 64 first)


@dataclass
class LtcFrame:
    timecode: Timecode
    user_bits: bytes  # 4 bytes, BG1..BG8 packed
    sample_start: int
    sample_end: int
    polarity: int


def _bcd(n: int) -> tuple[int, int]:
    return n % 10, n // 10


def pack_bits(tc: Timecode, user_bits: bytes = b"\x00\x00\x00\x00") -> str:
    if len(user_bits) != 4:
        raise ValueError("user_bits must be 4 bytes")
    fu, ft = _bcd(tc.frames)
    su, st = _bcd(tc.seconds)
    mu, mt = _bcd(tc.minutes)
    hu, ht = _bcd(tc.hours)
    bg = []
    for b in user_bits:
        bg.append(b & 0x0F)
        bg.append((b >> 4) & 0x0F)

    bits = [0] * 80

    def nib(start, val, n=4):
        for i in range(n):
            bits[start + i] = (val >> i) & 1

    nib(0, fu)
    nib(4, bg[0])
    nib(8, ft, 2)
    bits[10] = 1 if tc.drop_frame else 0
    bits[11] = 0  # color frame
    nib(12, bg[1])
    nib(16, su)
    nib(20, bg[2])
    nib(24, st, 3)
    bits[27] = 0  # polarity correction, set later if needed
    nib(28, bg[3])
    nib(32, mu)
    nib(36, bg[4])
    nib(40, mt, 3)
    bits[43] = 0
    nib(44, bg[5])
    nib(48, hu)
    nib(52, bg[6])
    nib(56, ht, 2)
    bits[58] = 0
    bits[59] = 0
    nib(60, bg[7])
    for i, ch in enumerate(SYNC):
        bits[64 + i] = 1 if ch == "1" else 0
    # polarity correction: even number of 0-bits? LTC uses bit 27 so that
    # the 80-bit word has an even number of 0-transitions; we set it after packing.
    if sum(1 for b in bits if b == 0) % 2 == 1:
        bits[27] ^= 1
    return "".join(str(b) for b in bits)


def unpack_bits(bitstr: str, nominal_fps: int) -> tuple[Timecode, bytes]:
    bits = [int(c) for c in bitstr]
    def slc(start, n):
        v = 0
        for i in range(n):
            v |= bits[start + i] << i
        return v
    frames = slc(0, 4) + 10 * slc(8, 2)
    seconds = slc(16, 4) + 10 * slc(24, 3)
    minutes = slc(32, 4) + 10 * slc(40, 3)
    hours = slc(48, 4) + 10 * slc(56, 2)
    df = bool(bits[10])
    ub = bytearray(4)
    ub[0] = slc(4, 4) | (slc(12, 4) << 4)
    ub[1] = slc(20, 4) | (slc(28, 4) << 4)
    ub[2] = slc(36, 4) | (slc(44, 4) << 4)
    ub[3] = slc(52, 4) | (slc(60, 4) << 4)
    return Timecode(hours, minutes, seconds, frames, df, nominal_fps), bytes(ub)


def encode_bmc(bitstr: str, samples_per_bit: float, phase: int = 1) -> list[float]:
    """Biphase mark: transition at every bit start; extra mid-bit transition for 1."""
    out: list[float] = []
    level = 0.5 if phase > 0 else -0.5
    pos = 0.0
    # generate at integer sample indices
    total = int(round(samples_per_bit * len(bitstr)))
    # We'll construct by walking bits
    samples: list[float] = []
    for i, ch in enumerate(bitstr):
        # transition at start
        level = -level
        half = samples_per_bit / 2.0
        n0 = int(round((i + 0.5) * samples_per_bit)) - int(round(i * samples_per_bit))
        n1 = int(round((i + 1) * samples_per_bit)) - int(round((i + 0.5) * samples_per_bit))
        samples.extend([level] * max(n0, 0))
        if ch == "1":
            level = -level
        samples.extend([level] * max(n1, 0))
    return samples



def decode_bmc(samples: list[float], sample_rate: int, nominal_fps: int) -> list[LtcFrame]:
    """Recover LTC frames by sampling biphase levels at a nominal bit period and hunting the sync word."""
    if not samples:
        return []
    spb = sample_rate / (80.0 * nominal_fps)
    if spb < 4:
        return []
    best: list[LtcFrame] = []
    # Try a handful of phase offsets within one bit.
    n_phase = max(4, int(spb))
    for phase_i in range(n_phase):
        phase = phase_i * (spb / n_phase)
        bits: list[str] = []
        starts: list[int] = []
        t = phase
        while t + spb <= len(samples) - 1:
            i1 = int(t + spb * 0.25)
            i2 = int(t + spb * 0.75)
            if i2 >= len(samples):
                break
            v1 = samples[i1]
            v2 = samples[i2]
            # '1' has a mid-bit transition, so the two half-bit midpoints have opposite sign.
            bit = "1" if (v1 * v2) < 0 else "0"
            bits.append(bit)
            starts.append(int(t))
            t += spb
        bitstr = "".join(bits)
        frames: list[LtcFrame] = []
        pos = 0
        seen_starts = set()
        while True:
            j = bitstr.find(SYNC, pos)
            if j < 0:
                break
            start = j - 64
            if start >= 0 and start + 80 <= len(bitstr) and start not in seen_starts:
                word = bitstr[start : start + 80]
                if word[64:80] == SYNC:
                    try:
                        tc, ub = unpack_bits(word, nominal_fps)
                        s0 = starts[start]
                        s1 = starts[min(start + 79, len(starts) - 1)]
                        frames.append(LtcFrame(tc, ub, s0, s1, 1))
                        seen_starts.add(start)
                    except Exception:
                        pass
            pos = j + 1
        if len(frames) > len(best):
            best = frames
    return best
