"""End-to-end test of the session flow against a simulated scale:
subscribe -> clock command -> streamed indications -> merged dump.
No BLE stack needed; the fake client speaks the same bleak surface.
"""
import asyncio
import types

from bleak.exc import BleakError

from scalebridge import client, gatt
from scalebridge.client import Scale

u = bytes.fromhex

PERSON_HEX = "845302800134b6e0000000000000000000000000"
WEIGHT_HEX = "1d8c1e00fe6e0aa056451100ff020900000000"
BODY_HEX = "6f6e0aa05602440ab8f07ff26bf11ef0000000"
WEIGHT_HEX2 = "1d961e00fe72fe9f56291100ff020900000000"

DUMP = [(gatt.CHAR_PERSON, u(PERSON_HEX)),
        (gatt.CHAR_WEIGHT, u(WEIGHT_HEX2)),
        (gatt.CHAR_WEIGHT, u(WEIGHT_HEX)),
        (gatt.CHAR_BODY, u(BODY_HEX))]


class FakeChar:
    def __init__(self, uuid, properties):
        self.uuid = uuid.lower()
        self.properties = properties


class FakeClient:
    def __init__(self, records, delay=0.01, fail_write=False):
        chars = [FakeChar(x, ["indicate"]) for x in gatt.DATA_CHARS]
        chars.append(FakeChar(gatt.CHAR_COMMAND, ["write"]))

        class S:
            def get_characteristic(self, uuid):
                return next((c for c in chars if c.uuid == uuid.lower()),
                            None)
        self.services = S()
        self.callbacks = {}
        self.records = records
        self.delay = delay
        self.fail_write = fail_write
        self.written = []

    async def start_notify(self, uuid, callback):
        self.callbacks[uuid.lower()] = callback

    async def write_gatt_char(self, char, data, response=True):
        self.written.append(bytes(data))
        loop = asyncio.get_running_loop()
        loop.create_task(self._stream())
        if self.fail_write:
            # stall, then error -- but the indications still flow
            raise BleakError("scale withheld the write response")

    async def _stream(self):
        for uuid, payload in self.records:
            await asyncio.sleep(self.delay)
            self.callbacks[uuid](FakeChar(uuid, []), bytearray(payload))


async def run_dump(fake):
    scale = Scale("AA:BB:CC:DD:EE:FF", epoch="unix")
    scale._client = fake  # skip real connect()
    dump = await scale.dump(idle_timeout=0.3, max_time=5)
    scale._client = None
    return dump


async def test_full_dump_session():
    fake = FakeClient(DUMP)
    dump = await run_dump(fake)
    # clock command: 0x02 + 4-byte LE unix time
    assert len(fake.written) == 1
    assert fake.written[0][0] == 0x02 and len(fake.written[0]) == 5
    assert len(dump.persons) == 1 and dump.persons[0].person == 2
    assert len(dump.readings) == 2
    merged = dump.readings[-1]
    assert (merged.weight_kg, merged.fat_pct, merged.kcal) == \
        (78.2, 18.4, 2628)
    assert merged.profile is not None and merged.bmi == 23.6


async def test_write_timeout_does_not_kill_the_session():
    # Reference clients saw the scale stall the command write while it
    # streams; we must still collect the indications.
    fake = FakeClient(DUMP, fail_write=True)
    dump = await run_dump(fake)
    assert len(dump.readings) == 2


async def test_collect_returns_when_stream_goes_quiet():
    fake = FakeClient(DUMP)
    scale = Scale("x", epoch="unix")
    scale._client = fake
    await scale.subscribe()
    await scale.sync_clock()
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await scale.collect(idle_timeout=0.2, max_time=10)
    assert loop.time() - t0 < 2.0  # idle timeout, not the hard cap


async def test_max_time_caps_a_stuck_session():
    fake = FakeClient([], delay=0)
    scale = Scale("x")
    scale._client = fake
    await scale.subscribe()
    t0 = asyncio.get_running_loop().time()
    await scale.collect(idle_timeout=5, max_time=0.2)
    assert asyncio.get_running_loop().time() - t0 < 1.0


async def test_sync_clock_subtracts_2010_offset_for_2010_firmware():
    import time
    fake = FakeClient([])
    scale = Scale("x", epoch="2010")
    scale._client = fake
    await scale.sync_clock()
    sent = int.from_bytes(fake.written[0][1:], "little")
    assert abs((time.time() - 1_262_304_000) - sent) < 60


# -- watch_scales session loop --------------------------------------------

class WatchScale:
    """Fake client.Scale standing in for repeated wake-up sessions."""
    instances = []
    sessions = 0
    fail_first_connect = False

    def __init__(self, address, epoch="auto", **kw):
        self.address = address
        WatchScale.instances.append(self)

    async def connect(self):
        if WatchScale.fail_first_connect and WatchScale.instances.index(
                self) == 0:
            raise BleakError("scale went back to sleep")

    async def disconnect(self):
        pass

    async def dump(self, idle_timeout=6.0, max_time=60.0):
        WatchScale.sessions += 1
        from scalebridge.models import Dump, Reading
        return Dump(readings=[Reading(person=6, timestamp=100 + i)
                              for i in range(WatchScale.sessions)])


async def _no_sleep(_seconds):
    return None


async def test_watch_dedupes_across_wake_sessions(monkeypatch):
    dev = types.SimpleNamespace(address="AA:BB:CC:DD:EE:FF")
    WatchScale.instances = []
    WatchScale.sessions = 0
    WatchScale.fail_first_connect = False

    calls = {"n": 0}

    async def fake_find(timeout=5.0, address=None, all_devices=False):
        calls["n"] += 1
        if calls["n"] > 3:
            raise asyncio.CancelledError      # end the infinite loop
        return [(dev, None)]
    monkeypatch.setattr(client, "find_scales", fake_find)
    monkeypatch.setattr(client, "Scale", WatchScale)
    monkeypatch.setattr(client.asyncio, "sleep", _no_sleep)

    got = []
    try:
        async for r in client.watch_scales(reconnect_delay=0):
            got.append(r.timestamp)
    except asyncio.CancelledError:
        pass
    # sessions deliver 1, 2, 3, 4 readings — only never-seen
    # (person, timestamp) keys come through
    assert got == [100, 101, 102]


async def test_watch_survives_failed_session(monkeypatch):
    dev = types.SimpleNamespace(address="AA:BB:CC:DD:EE:FF")
    WatchScale.instances = []
    WatchScale.sessions = 0
    WatchScale.fail_first_connect = True

    calls = {"n": 0}

    async def fake_find(timeout=5.0, address=None, all_devices=False):
        calls["n"] += 1
        if calls["n"] > 3:
            raise asyncio.CancelledError
        return [(dev, None)]
    monkeypatch.setattr(client, "find_scales", fake_find)
    monkeypatch.setattr(client, "Scale", WatchScale)
    monkeypatch.setattr(client.asyncio, "sleep", _no_sleep)

    got = []
    try:
        async for r in client.watch_scales(reconnect_delay=0):
            got.append(r.timestamp)
    except asyncio.CancelledError:
        pass
    assert got == [100, 101]       # first session died, two delivered
    WatchScale.fail_first_connect = False


async def test_device_info_reads_device_info_service():
    class InfoFake(FakeClient):
        def __init__(self):
            super().__init__([])

            class S2:
                def get_characteristic(self, uuid):
                    return object() if uuid[4:8] in (
                        "2a29", "2a24", "2a26") else None
            self.services = S2()

        async def read_gatt_char(self, uuid):
            return {"2a29": b"Medisana\x00", "2a24": b"BS440",
                    "2a26": b"B.8"}[uuid[4:8]]

    scale = Scale("x")
    scale._client = InfoFake()
    assert await scale.device_info() == {"manufacturer": "Medisana",
                                         "model": "BS440",
                                         "firmware": "B.8"}
