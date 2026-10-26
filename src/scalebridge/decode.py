"""Pure decoders for the three BS440 indication records.

All multibyte values are unsigned little-endian.  Records are recognised
by their fixed first byte (validity check); a record that fails the
check is rejected rather than half-parsed, so firmware surprises surface
as errors instead of plausible-looking nonsense.

The byte layout was originally reverse-engineered by keptenkurk; see the
protocol section in README.md for the full table and credits.
"""
from __future__ import annotations

import struct
import time

PERSON_MAGIC = 0x84
WEIGHT_MAGIC = 0x1D
BODY_MAGIC = 0x6F

# On some models (BS410, BS444, and BS440 units advertising 0202B6*/
# 013197*/013198* names) the scale's clock starts at 2010-01-01, so
# timestamps are 1262304000 seconds behind real Unix time.
EPOCH_2010_OFFSET = 1_262_304_000

_GENDER = {1: "male", 2: "female"}
_ACTIVITY = {0: "normal", 3: "high"}

EPOCH_MODES = ("auto", "unix", "2010")


def sanitize_timestamp(ts: int, epoch: str = "auto",
                       now: float | None = None) -> int:
    """Map a scale timestamp onto real Unix time.

    auto: pick whichever candidate (raw, or shifted by the 2010 epoch
    offset) lands within +-90 days of now -- the same heuristic openScale
    uses, robust even when the scale's RTC was never set.  Neither near
    now: tiny values are treated as a 2010-based never-set clock, larger
    ones are trusted as raw Unix (don't flip).
    """
    if epoch not in EPOCH_MODES:
        raise ValueError(f"epoch must be one of {EPOCH_MODES}, got {epoch!r}")
    if epoch == "unix":
        return ts
    if epoch == "2010":
        return ts + EPOCH_2010_OFFSET
    now = time.time() if now is None else now
    near = 90 * 24 * 3600
    if abs(ts - now) <= near:
        return ts
    if abs(ts + EPOCH_2010_OFFSET - now) <= near:
        return ts + EPOCH_2010_OFFSET
    return ts + EPOCH_2010_OFFSET if ts < EPOCH_2010_OFFSET else ts


def decode_person(data: bytes | bytearray) -> dict:
    """Person profile record (characteristic 0x8A82, magic 0x84)."""
    if len(data) < 9:
        raise ValueError(f"person record too short: {len(data)} bytes")
    magic, person, gender, age, size, activity = struct.unpack_from(
        "BxBxBBBxB", bytes(data))
    if magic != PERSON_MAGIC:
        raise ValueError(f"bad person magic: 0x{magic:02x}")
    return {
        "person": person,
        "gender": _GENDER.get(gender, f"unknown({gender})"),
        "age": age,
        "size_cm": size,
        "activity": _ACTIVITY.get(activity, f"unknown({activity})"),
    }


def decode_weight(data: bytes | bytearray, epoch: str = "auto") -> dict:
    """Weight record (characteristic 0x8A21, magic 0x1d)."""
    if len(data) < 14:
        raise ValueError(f"weight record too short: {len(data)} bytes")
    magic, weight, ts, person = struct.unpack_from("<BHxxIxxxxB", bytes(data))
    if magic != WEIGHT_MAGIC:
        raise ValueError(f"bad weight magic: 0x{magic:02x}")
    return {
        "person": person,
        "timestamp": sanitize_timestamp(ts, epoch),
        "weight_kg": weight / 100.0,
    }


def decode_body(data: bytes | bytearray, epoch: str = "auto") -> dict:
    """Body-composition record (characteristic 0x8A22, magic 0x6f).

    The percentage fields arrive as u16 whose high nibble is always
    0xF; the low 12 bits hold value*10.  kcal arrives as plain u16.
    """
    if len(data) < 16:
        raise ValueError(f"body record too short: {len(data)} bytes")
    magic, ts, person, kcal, fat, tbw, muscle, bone = struct.unpack_from(
        "<BIBHHHHH", bytes(data))
    if magic != BODY_MAGIC:
        raise ValueError(f"bad body magic: 0x{magic:02x}")
    pct = lambda v: (v & 0x0FFF) / 10.0  # noqa: E731
    return {
        "person": person,
        "timestamp": sanitize_timestamp(ts, epoch),
        "kcal": kcal,
        "fat_pct": pct(fat),
        "tbw_pct": pct(tbw),
        "muscle_pct": pct(muscle),
        "bone_pct": pct(bone),
    }
