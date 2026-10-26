"""find_scales/cmd_scan must agree on the (BLEDevice, AdvertisementData)
tuple shape that bleak's discover(return_adv=True) produces -- a real
regression: scanning crashed on the first match when a bare device list
was assumed.  Also pins client-side filtering: some bleak backends
ignore the `cb` filter and return everything (live-Pi finding)."""
import types

import scalebridge.cli as cli
import scalebridge.client as client


class FakeDevice:
    def __init__(self, address, name):
        self.address = address
        self.name = name


class FakeAdv:
    def __init__(self, local_name, rssi, service_uuids=()):
        self.local_name = local_name
        self.rssi = rssi
        self.service_uuids = list(service_uuids)


JUNK = types.SimpleNamespace(address="00:19:01:C8:BE:8A", name="YamahaAV")
SCALE = types.SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="BS440")
OTHER = types.SimpleNamespace(address="11:22:33:44:55:66", name=None)


async def test_cmd_scan_prints_tuple_entries(monkeypatch, capsys):
    async def fake_find(timeout=10.0, address=None, all_devices=False):
        return [(FakeDevice("AA:BB:CC:DD:EE:FF", "BS440"),
                 FakeAdv("BS440", -63)),
                (FakeDevice("11:22:33:44:55:66", None),
                 FakeAdv("BS 440", -70))]
    monkeypatch.setattr(cli, "find_scales", fake_find)
    args = types.SimpleNamespace(timeout=1.0, all=False)
    await cli.cmd_scan(args)
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("AA:BB:CC:DD:EE:FF  BS440")
    assert "via=name" in out[0]
    assert "BS 440" in out[1]  # falls back to advertisement local_name


async def test_cmd_scan_empty(monkeypatch, capsys):
    async def fake_find(timeout=10.0, address=None, all_devices=False):
        return []
    monkeypatch.setattr(cli, "find_scales", fake_find)
    await cli.cmd_scan(types.SimpleNamespace(timeout=1.0, all=False))
    out = capsys.readouterr().out
    assert "no scales found" in out and "--all" in out


async def test_find_scales_filters_client_side(monkeypatch):
    """Even if discover hands us the whole RF environment, non-matches
    (YamahaAV, plain-GAP 'unpaired' modules) must be dropped."""
    discovered = {
        "a": (JUNK, FakeAdv("YamahaAV", -48,
                            ["945ca2b0-0000-1000-8000-00805f9b34fb"])),
        "b": (SCALE, FakeAdv("BS440", -55)),
        "c": (OTHER, FakeAdv("unpaired", -51,
                             ["00001800-0000-1000-8000-00805f9b34fb"])),
        "d": (OTHER, FakeAdv("mystery", -60,
                             ["000078b2-0000-1000-8000-00805f9b34fb"])),
    }

    class FakeScanner:
        @staticmethod
        async def discover(timeout=5.0, return_adv=False, **kw):
            return discovered
    monkeypatch.setattr(client, "BleakScanner", FakeScanner)

    found = await client.find_scales(timeout=1)
    addresses = {d.address for d, _ in found}
    assert addresses == {"AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"}  # b, d

    everything = await client.find_scales(timeout=1, all_devices=True)
    assert len(everything) == 4
