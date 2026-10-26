"""find_scales/cmd_scan must agree on the (BLEDevice, AdvertisementData)
tuple shape that bleak's discover(return_adv=True) produces -- a real
regression: scanning crashed on the first match when a bare device list
was assumed."""
import types

import scalebridge.cli as cli


class FakeDevice:
    def __init__(self, address, name):
        self.address = address
        self.name = name


class FakeAdv:
    def __init__(self, local_name, rssi):
        self.local_name = local_name
        self.rssi = rssi


async def test_cmd_scan_prints_tuple_entries(monkeypatch, capsys):
    async def fake_find(timeout=10.0, address=None):
        return [(FakeDevice("AA:BB:CC:DD:EE:FF", "BS440"),
                 FakeAdv("BS440", -63)),
                (FakeDevice("11:22:33:44:55:66", None),
                 FakeAdv("BS 440", -70))]
    monkeypatch.setattr(cli, "find_scales", fake_find)
    args = types.SimpleNamespace(timeout=1.0)
    await cli.cmd_scan(args)
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("AA:BB:CC:DD:EE:FF  BS440")
    assert "-63" in out[0]
    assert "BS 440" in out[1]  # falls back to advertisement local_name


async def test_cmd_scan_empty(monkeypatch, capsys):
    async def fake_find(timeout=10.0, address=None):
        return []
    monkeypatch.setattr(cli, "find_scales", fake_find)
    await cli.cmd_scan(types.SimpleNamespace(timeout=1.0))
    assert "no scales found" in capsys.readouterr().out
