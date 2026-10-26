"""Headless tests for the client's ingest/merge logic (no BLE needed)."""
import types

from scalebridge import gatt
from scalebridge.client import Scale, match_reason, matches_name, predict_epoch

WEIGHT_HEX = "1d8c1e00fe6e0aa056451100ff020900000000"
WEIGHT_HEX2 = "1d961e00fe72fe9f56291100ff020900000000"  # p2, later ts
BODY_HEX = "6f6e0aa05602440ab8f07ff26bf11ef0000000"
PERSON_HEX = "845302800134b6e0000000000000000000000000"

u = bytes.fromhex


def make_scale():
    s = Scale("AA:BB:CC:DD:EE:FF", epoch="unix")
    s._ingest(gatt.CHAR_PERSON, u(PERSON_HEX))
    s._ingest(gatt.CHAR_WEIGHT, u(WEIGHT_HEX))
    s._ingest(gatt.CHAR_BODY, u(BODY_HEX))
    s._ingest(gatt.CHAR_WEIGHT, u(WEIGHT_HEX2))
    return s


def test_weight_and_body_merge_into_one_reading():
    dump = make_scale().result()
    assert len(dump.readings) == 2
    old, new = dump.readings  # sorted ascending by timestamp
    assert old.weight_kg == 78.3 and old.kcal is None  # weight-only record
    assert new.weight_kg == 78.2 and new.kcal == 2628  # merged pair
    assert new.fat_pct == 18.4


def test_duplicate_records_collapse():
    s = make_scale()
    s._ingest(gatt.CHAR_WEIGHT, u(WEIGHT_HEX))  # same indication twice
    assert len(s.result().readings) == 2


def test_profiles_attached_for_bmi():
    dump = make_scale().result()
    r = dump.readings[-1]
    assert r.profile is not None and r.profile.size_cm == 182
    assert r.bmi == round(78.2 / 1.82 ** 2, 1)


def test_garbage_is_rejected_not_merged():
    s = Scale("x")
    assert s._ingest(gatt.CHAR_WEIGHT, u("ff0000")) is False
    assert s.readings == {}
    assert len(s.unhandled) == 1


def test_unknown_uuid_lands_in_unhandled():
    s = Scale("x")
    assert s._ingest("0000ffff-0000-1000-8000-00805f9b34fb", u("0102")) \
        is False
    assert len(s.unhandled) == 1


def test_name_matching():
    assert matches_name("BS440")
    assert matches_name("BS 440")
    assert matches_name("Medisana scale")
    assert not matches_name("QN-Scale1")
    assert not matches_name(None)


def test_match_reason():
    d = types.SimpleNamespace(name=None)
    a = types.SimpleNamespace(local_name="BS440", service_uuids=[])
    assert match_reason(d, a) == "name"
    a = types.SimpleNamespace(
        local_name="0203B6ABC8A438C1A4", service_uuids=[])
    assert match_reason(d, a) == "name"  # hex-token Medisana name
    a = types.SimpleNamespace(
        local_name="unpaired",
        service_uuids=["000078b2-0000-1000-8000-00805f9b34fb"])
    assert match_reason(d, a) == "78b2"
    a = types.SimpleNamespace(local_name="YamahaAV",
                              service_uuids=["0000110c-0000-1000-8000-00805f9b34fb"])
    assert match_reason(d, a) is None


def test_predict_epoch():
    assert predict_epoch("0203B6ABC8A438C1A4") == "unix"
    assert predict_epoch("0202B61234567890") == "2010"
    assert predict_epoch("013197XYZ") == "2010"
    assert predict_epoch("BS440") is None


def test_reading_str_has_one_decimal():
    r = make_scale().result().readings[-1]
    line = str(r)
    assert "fat 18.4 " in line and "0.000000" not in line


def test_empty_person_slots_are_dropped():
    s = Scale("x")
    junk = bytearray(u(PERSON_HEX))
    junk[2] = 0xFF                      # unoccupied memory slot
    assert s._ingest(gatt.CHAR_PERSON, junk) is True
    assert s.persons == {}
    assert s._ingest(gatt.CHAR_PERSON, u(PERSON_HEX)) is True
    assert set(s.persons) == {2}


def test_guest_slot_labeling():
    from scalebridge.models import Reading
    g = Reading(person=255, timestamp=1793047292, weight_kg=148.4)
    assert g.slot_name == "guest"
    assert g.to_dict()["slot"] == "guest"
    assert "guest" in str(g)
    assert Reading(person=6, timestamp=1).slot_name == "6"
