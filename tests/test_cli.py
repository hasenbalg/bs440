"""CLI command bodies against fake Scales (no BLE stack)."""
import json
import types

import scalebridge.cli as cli
from scalebridge.models import Dump, Person, Reading

P = Person(person=6, gender="male", age=39, size_cm=181, activity="normal")
R1 = Reading(person=6, timestamp=1793047005, weight_kg=147.8, kcal=2740,
             fat_pct=48.9, tbw_pct=43.0, muscle_pct=37.0, bone_pct=3.7,
             profile=P)
R2 = Reading(person=255, timestamp=1793047292, weight_kg=148.4, kcal=0,
             fat_pct=0.0, tbw_pct=0.0, muscle_pct=0.0, bone_pct=0.0)


def fake_scale_cls(dump, info=None):
    class FakeScale:
        services = []
        unhandled = []

        def __init__(self, address, epoch="auto", **kw):
            self.address, self.epoch = address, epoch

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def dump(self, idle_timeout=6.0, max_time=60.0):
            return dump

        async def subscribe(self):
            pass

        async def sync_clock(self):
            pass

        async def collect(self, idle_timeout=6.0):
            pass

        def result(self):
            return dump

        async def device_info(self):
            return info or {}
    return FakeScale


def args(**kw):
    base = dict(address="AA:BB:CC:DD:EE:FF", epoch="auto", idle=1.0,
                max=2.0, csv=None, json=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


async def test_cmd_dump_plain_json_csv(monkeypatch, capsys, tmp_path):
    dump = Dump(persons=[P], readings=[R1, R2])
    monkeypatch.setattr(cli, "Scale", fake_scale_cls(dump))

    await cli.cmd_dump(args())
    out = capsys.readouterr().out
    assert "147.80kg" in out and "guest" in out and "2 readings" in out

    await cli.cmd_dump(args(json=True))
    data = json.loads(capsys.readouterr().out)
    assert data[0]["bmi"] and data[1]["slot"] == "guest"

    f = tmp_path / "out.csv"
    await cli.cmd_dump(args(csv=str(f)))
    lines = f.read_text().strip().splitlines()
    assert lines[0].startswith("datetime,timestamp,person,weight_kg,bmi")
    assert len(lines) == 3          # header + 2 readings
    assert ",male,39,181," in lines[1]


async def test_cmd_dump_empty_hints(monkeypatch, capsys):
    monkeypatch.setattr(cli, "Scale",
                        fake_scale_cls(Dump(persons=[], readings=[])))
    await cli.cmd_dump(args())
    assert "0 readings" in capsys.readouterr().err


async def test_cmd_watch_json_lines(monkeypatch, capsys):
    async def fake_watch(address=None, epoch="auto", idle_timeout=6.0,
                         **kw):
        for r in (R1, R2):
            yield r
    monkeypatch.setattr(cli, "watch_scales", fake_watch)
    await cli.cmd_watch(args(json=True))
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["weight_kg"] == 147.8
    assert "guest" in lines[1]


async def test_cmd_info_maps_gatt_and_dump(monkeypatch, capsys):
    char = types.SimpleNamespace(uuid="00008a21-0000-1000-8000-00805f9b34fb",
                                 properties=["indicate"])
    service = types.SimpleNamespace(characteristics=[char])

    class S(fake_scale_cls(Dump(persons=[P], readings=[R1]),
                           info={"manufacturer": "Transtek"})):
        services = [service]
    monkeypatch.setattr(cli, "Scale", S)

    await cli.cmd_info(args())
    out = capsys.readouterr().out
    assert "[I]" in out
    assert "manufacturer: Transtek" in out
    assert "1 person profiles, 1 readings" in out
