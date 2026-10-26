"""hunt identifies the scale by GATT markers, not advertisement names."""
import types

import scalebridge.cli as cli


async def test_hunt_finds_scale_among_strangers(monkeypatch, capsys):
    devices = [
        (types.SimpleNamespace(address="00:19:01:C8:BE:8A", name="YamahaAV"),
         types.SimpleNamespace(local_name=None, rssi=-50)),
        (types.SimpleNamespace(address="A4:C1:38:27:BB:93", name="unpaired"),
         types.SimpleNamespace(local_name="unpaired", rssi=-51)),
        (types.SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name=None),
         types.SimpleNamespace(local_name=None, rssi=-60)),
    ]

    async def fake_find(timeout=10.0, address=None, all_devices=False):
        return devices
    gatt_map = {
        "A4:C1:38:27:BB:93": {"1800", "1801", "2a00"},      # plain module
        "AA:BB:CC:DD:EE:FF": {"1800", "1801", "8a21",
                              "8a22", "8a81", "8a82"},      # the scale
    }

    async def fake_probe(address, timeout=10.0):
        chars = gatt_map.get(address)
        return (chars, None) if chars else (None, "ConnectTimeout: x")
    monkeypatch.setattr(cli, "find_scales", fake_find)
    monkeypatch.setattr(cli, "probe_device", fake_probe)

    args = types.SimpleNamespace(timeout=1, probe_timeout=1, skip=None)
    await cli.cmd_hunt(args)
    out = capsys.readouterr().out
    assert "skip  00:19:01:C8:BE:8A" in out          # name blacklist
    assert "BS440 SCALE (4/4 markers)" in out
    assert "found it:  scalebridge info AA:BB:CC:DD:EE:FF" in out
    assert "A4:C1:38:27:BB:93" in out and "8a21" not in \
        out.split("A4:C1:38:27:BB:93")[1].splitlines()[0]


async def test_hunt_skip_list_and_none_found(monkeypatch, capsys):
    devices = [(types.SimpleNamespace(address="11:22:33:44:55:66",
                                      name="thing"),
                types.SimpleNamespace(local_name="thing", rssi=-60))]

    async def fake_find(timeout=10.0, address=None, all_devices=False):
        return devices

    async def fake_probe(address, timeout=10.0):
        return None, "Disconnected: no answer"
    monkeypatch.setattr(cli, "find_scales", fake_find)
    monkeypatch.setattr(cli, "probe_device", fake_probe)

    args = types.SimpleNamespace(timeout=1, probe_timeout=1,
                                 skip="11:22:33:44:55:66")
    await cli.cmd_hunt(args)
    out = capsys.readouterr().out
    assert "(--skip)" in out
    assert "no scale found" in out
