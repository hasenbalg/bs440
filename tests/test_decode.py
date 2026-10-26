"""Golden-record tests: every packet here is a real indication captured
by the reference project (keptenkurk/BS440 blog, part 3) and decoded by
hand against the documented byte layout."""
import pytest

from scalebridge.decode import (
    BODY_MAGIC,
    PERSON_MAGIC,
    WEIGHT_MAGIC,
    decode_body,
    decode_person,
    decode_weight,
    sanitize_timestamp,
)

# 0x25 person indication from the blog writeup
PERSON_HEX = "845302800134b6e0000000000000000000000000"
# one matching weight/body pair from the same dump
WEIGHT_HEX = "1d8c1e00fe6e0aa056451100ff020900000000"
BODY_HEX = "6f6e0aa05602440ab8f07ff26bf11ef0000000"

u = bytes.fromhex


class TestPerson:
    def test_golden(self):
        p = decode_person(u(PERSON_HEX))
        assert p == {"person": 2, "gender": "male", "age": 52,
                     "size_cm": 182, "activity": "normal"}

    def test_female_high_activity(self):
        # byte4=02 (female), byte8=03 (high activity)
        raw = bytearray(u(PERSON_HEX))
        raw[4], raw[8] = 0x02, 0x03
        p = decode_person(raw)
        assert p["gender"] == "female"
        assert p["activity"] == "high"

    def test_bad_magic(self):
        with pytest.raises(ValueError, match="magic"):
            decode_person(u("855302800134b6e00000"))

    def test_too_short(self):
        with pytest.raises(ValueError, match="short"):
            decode_person(u("845302"))


class TestWeight:
    def test_golden(self):
        w = decode_weight(u(WEIGHT_HEX), epoch="unix")
        assert w["person"] == 2
        assert w["weight_kg"] == pytest.approx(78.20)
        # bytes 5..8 little-endian = 0x56a00a6e = 2015-09-21
        assert w["timestamp"] == 0x56A00A6E

    def test_bad_magic(self):
        with pytest.raises(ValueError, match="magic"):
            decode_weight(u("1e8c1e00fe6e0aa056451100ff02"))


class TestBody:
    def test_golden(self):
        b = decode_body(u(BODY_HEX), epoch="unix")
        assert b["person"] == 2
        assert b["timestamp"] == 0x56A00A6E
        assert b["kcal"] == 2628
        assert b["fat_pct"] == pytest.approx(18.4)
        assert b["tbw_pct"] == pytest.approx(63.9)
        assert b["muscle_pct"] == pytest.approx(36.3)
        assert b["bone_pct"] == pytest.approx(3.0)

    def test_high_nibble_stripped(self):
        # percentages must survive whatever the 0xF nibble carries
        raw = bytearray(u(BODY_HEX))
        raw[0] = BODY_MAGIC
        b = decode_body(raw, epoch="unix")
        assert 0 <= b["fat_pct"] <= 100

    def test_bad_magic(self):
        with pytest.raises(ValueError, match="magic"):
            decode_body(u("6e6e0aa05602440ab8f07ff26bf11ef0"))


class TestEpoch:
    def test_auto_shifts_2010_clocks(self):
        # never-set clock on a 2010-epoch scale: 0 -> 2010-01-01
        assert sanitize_timestamp(0, "auto") == 1_262_304_000
        # a real Unix timestamp is untouched
        assert sanitize_timestamp(0x56A00A6E, "auto") == 0x56A00A6E

    def test_explicit_modes(self):
        assert sanitize_timestamp(100, "2010") == 1_262_304_100
        assert sanitize_timestamp(100, "unix") == 100

    def test_bad_mode(self):
        with pytest.raises(ValueError):
            sanitize_timestamp(1, "gps")


class TestMergeKey:
    """The client merges weight+body by (person, timestamp)."""

    def test_pair_matches(self):
        w = decode_weight(u(WEIGHT_HEX), epoch="unix")
        b = decode_body(u(BODY_HEX), epoch="unix")
        assert (w["person"], w["timestamp"]) == (b["person"], b["timestamp"])


def test_magics_are_stable():
    assert (PERSON_MAGIC, WEIGHT_MAGIC, BODY_MAGIC) == (0x84, 0x1D, 0x6F)
