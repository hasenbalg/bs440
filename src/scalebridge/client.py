"""Async BLE client for the scale (bleak).

Session model, following the protocol reverse-engineering credits in
README.md: the scale wakes and advertises when stepped on; on connect
we subscribe to the three data characteristics (they INDICATE), then
write `0x02 + unix_now(u32 LE)` to the command register 0x8A81.  That
syncs the scale's RTC and makes it dump its stored history (up to 30
measurements per person slot) as indications.  A live weigh-in simply
shows up in that dump as the newest record, which makes `watch` a
simple "dump, dedupe, repeat" loop.

The command write is deliberately tolerant: the reference client saw
the scale ACK the ATT write only after (or instead of) finishing the
dump, so a timeout there is logged and ignored -- the indications are
what we actually wait for.
"""
from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

from . import gatt
from .decode import EPOCH_2010_OFFSET, decode_body, decode_person, decode_weight
from .models import Dump, Person, Reading

log = logging.getLogger("scalebridge.client")

# Advertisement names of scales speaking this protocol.  Many Medisana
# units advertise a hex token, not the model name; these prefixes come
# from openScale's MedisanaBs44xHandler name mapping (and Frank's live
# BS440 advertises "0203B6ABC8A438C1A4").
NAME_PATTERNS = ["bs440", "bs441", "bs442", "bs410", "bs430", "bs444",
                 "ss02", "medisana*",
                 "013197*", "013198*", "0202b6*", "0203b*"]

INDICATION_CAPABLE = {"indicate", "notify"}

# Advertise-name prefixes -> firmware epoch family (openScale mapping).
_EPOCH_NAME_PREFIXES = [("0203b", "unix"),
                        ("013197", "2010"), ("013198", "2010"),
                        ("0202b6", "2010")]


def predict_epoch(name: Optional[str]) -> Optional[str]:
    """Guess the firmware timestamp epoch from the advertisement name."""
    lname = (name or "").lower().strip()
    for prefix, mode in _EPOCH_NAME_PREFIXES:
        if lname.startswith(prefix):
            return mode
    return None


def matches_name(name: Optional[str]) -> bool:
    lname = (name or "").lower().strip().replace(" ", "")
    return any(fnmatch.fnmatch(lname, pat.replace(" ", ""))
               for pat in NAME_PATTERNS)


class Scale:
    """One GATT session with a BS440-family scale."""

    def __init__(self, address: str, epoch: str = "auto",
                 timeout: float = 30.0):
        self.address = address
        self.epoch = epoch
        self.timeout = timeout
        self._client: Optional[BleakClient] = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self.persons: dict[int, Person] = {}
        self.readings: dict[tuple, Reading] = {}
        self.unhandled: list[tuple[str, bytes]] = []

    # -- connection ----------------------------------------------------

    async def connect(self) -> None:
        self._client = BleakClient(self.address, timeout=self.timeout)
        await self._client.connect()
        log.info("connected to %s", self.address)

    async def disconnect(self) -> None:
        if self._client:
            try:
                await self._client.disconnect()
            except (BleakError, asyncio.TimeoutError):
                pass
            self._client = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()

    # -- discovery helpers ---------------------------------------------

    def _char(self, uuid: str):
        assert self._client, "not connected"
        char = self._client.services.get_characteristic(uuid)
        if char is None:
            raise BleakError(f"scale does not expose {uuid}")
        return char

    def data_char_uuids(self) -> list[str]:
        """Which of the three data characteristics this firmware exposes."""
        have = []
        for uuid in gatt.DATA_CHARS:
            if self._client.services.get_characteristic(uuid):
                have.append(uuid)
        return have

    # -- receiving ------------------------------------------------------

    def _on_indication(self, char, data: bytearray) -> None:
        self._queue.put_nowait((char.uuid.lower(), bytes(data)))

    async def subscribe(self) -> None:
        for uuid in self.data_char_uuids():
            await self._client.start_notify(uuid, self._on_indication)
            log.info("subscribed to %s", uuid)

    def _ingest(self, uuid: str, data: bytes) -> bool:
        """Feed one indication into the merge buffers. True if recognised."""
        try:
            if uuid == gatt.CHAR_PERSON:
                p = decode_person(data)
                self.persons[p["person"]] = Person(**p)
            elif uuid == gatt.CHAR_WEIGHT:
                w = decode_weight(data, self.epoch)
                r = self.readings.setdefault(
                    (w["person"], w["timestamp"]),
                    Reading(person=w["person"], timestamp=w["timestamp"]))
                r.weight_kg = w["weight_kg"]
            elif uuid == gatt.CHAR_BODY:
                b = decode_body(data, self.epoch)
                r = self.readings.setdefault(
                    (b["person"], b["timestamp"]),
                    Reading(person=b["person"], timestamp=b["timestamp"]))
                r.kcal = b["kcal"]
                r.fat_pct = b["fat_pct"]
                r.tbw_pct = b["tbw_pct"]
                r.muscle_pct = b["muscle_pct"]
                r.bone_pct = b["bone_pct"]
            else:
                self.unhandled.append((uuid, data))
                return False
        except ValueError as e:
            log.warning("undecodable record from %s: %s (%s)",
                        uuid, data.hex(), e)
            self.unhandled.append((uuid, data))
            return False
        return True

    # -- actions ---------------------------------------------------------

    async def sync_clock(self) -> None:
        """RTC sync = history dump trigger.

        2010-epoch firmware expects seconds since 2010-01-01 here
        (openScale subtracts the offset before writing); everything
        else gets real Unix time.
        """
        now = int(time.time())
        if self.epoch == "2010":
            now -= EPOCH_2010_OFFSET
        payload = b"\x02" + now.to_bytes(4, "little")
        char = self._char(gatt.CHAR_COMMAND)
        write_with_response = "write" in (char.properties or {})
        try:
            await self._client.write_gatt_char(
                char, payload, response=write_with_response)
            log.info("clock synced (history dump triggered)")
        except (asyncio.TimeoutError, BleakError) as e:
            # The scale often withholds the write response while it
            # streams the dump; indications keep coming regardless.
            log.info("command write did not complete (%s); "
                     "continuing to listen for indications", e)

    async def collect(self, idle_timeout: float = 6.0,
                      max_time: float = 60.0) -> None:
        """Drain indications until the stream goes quiet."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_time
        last = loop.time()
        while True:
            budget = min(idle_timeout - (loop.time() - last),
                         deadline - loop.time())
            if budget <= 0:
                return
            try:
                uuid, data = await asyncio.wait_for(
                    self._queue.get(), timeout=budget)
            except asyncio.TimeoutError:
                return
            self._ingest(uuid, data)
            last = loop.time()

    def result(self) -> Dump:
        dump = Dump(persons=[self.persons[k] for k in sorted(self.persons)],
                    readings=sorted(self.readings.values(),
                                    key=lambda r: r.timestamp))
        dump.attach_profiles()
        return dump

    async def dump(self, idle_timeout: float = 6.0,
                   max_time: float = 60.0) -> Dump:
        """Connect-time session: subscribe, trigger dump, collect, merge."""
        await self.subscribe()
        await self.sync_clock()
        await self.collect(idle_timeout=idle_timeout, max_time=max_time)
        return self.result()

    # -- diagnostics -------------------------------------------------------

    @property
    def services(self):
        """Raw bleak service collection (for GATT diagnostics)."""
        assert self._client, "not connected"
        return self._client.services

    async def device_info(self) -> dict[str, str]:
        info: dict[str, str] = {}
        if not self._client.services.get_characteristic(
                gatt.MANUFACTURER_NAME):
            return info
        for label, uuid in (("manufacturer", gatt.MANUFACTURER_NAME),
                            ("model", gatt.MODEL_NUMBER),
                            ("firmware", gatt.FIRMWARE_REVISION)):
            try:
                raw = await self._client.read_gatt_char(uuid)
                info[label] = raw.decode(errors="replace").strip("\x00 ")
            except (BleakError, asyncio.TimeoutError):
                pass
        return info


# -- scanning -------------------------------------------------------------

async def find_scales(timeout: float = 10.0,
                      address: Optional[str] = None,
                      all_devices: bool = False) -> list[tuple]:
    """Scan for BS440-family advertisements (or a specific address).

    Always returns a list of ``(BLEDevice, AdvertisementData | None)``
    tuples -- bleak's ``discover(return_adv=True)`` yields exactly that
    per device, so we normalize to it instead of leaking that shape.
    ``all_devices`` skips the filter (diagnostics: identify a scale that
    advertises under an unexpected name/service).
    """
    if address:
        device = await BleakScanner.find_device_by_address(
            address, timeout=timeout)
        return [(device, None)] if device else []

    devices = await BleakScanner.discover(timeout=timeout,
                                          return_adv=True)
    found = [(d, a) for d, a in devices.values()]
    if all_devices:
        return found
    # Filter ourselves: the `cb` filter argument's semantics vary across
    # bleak versions (on some backends its return value is ignored and
    # *all* devices are returned), so never trust it to exclude.
    return [(d, a) for d, a in found if match_reason(d, a)]


def match_reason(device, adv):
    """Why an advertisement looks like our scale family, or None.

    Returns "name" or the matched service UUID; surfaced in `scan`
    output because the 8080 service hint matches plenty of non-scale
    Chinese BLE modules too.
    """
    if matches_name(getattr(device, "name", None)
                    or getattr(adv, "local_name", None)):
        return "name"
    for u in getattr(adv, "service_uuids", None) or []:
        if u.lower() == gatt.SCALE_SERVICE:
            return "78b2"
    return None


def _short_uuids(adv) -> str:
    out = []
    for u in getattr(adv, "service_uuids", None) or []:
        u = u.lower()
        if u.endswith("-0000-1000-8000-00805f9b34fb"):
            out.append(u[4:8])
        else:
            out.append(u[:8])
    return ",".join(out)


def _mfg_ids(adv) -> str:
    keys = getattr(adv, "manufacturer_data", None) or {}
    return ",".join(f"{k:04x}" for k in keys)


def _scan_line(dev, adv, via) -> str:
    name = dev.name or getattr(adv, "local_name", None) or "(unnamed)"
    mfg = _mfg_ids(adv)
    extra = f"  mfg=[{mfg}]" if mfg else ""
    return (f"{dev.address}  {name:<20} rssi={getattr(adv, 'rssi', None)}"
            f"  via={via}  svcs=[{_short_uuids(adv)}]{extra}")


async def watch_scales(address: Optional[str] = None, epoch: str = "auto",
                       scan_timeout: float = 10.0, idle_timeout: float = 6.0,
                       reconnect_delay: float = 2.0):
    """Yield each *new* Reading as people step on the scale.

    Each advertisement wakes a fresh session; a full dump per wake-up is
    the robust way to catch the live weigh-in (the scale folds it into
    the history).  Readings already delivered are deduped by
    (person, timestamp).
    """
    seen: set[tuple] = set()
    first = True
    while True:
        found = await find_scales(timeout=scan_timeout if first else 5.0,
                                  address=address)
        first = False
        if not found:
            await asyncio.sleep(reconnect_delay)
            continue
        dev, _adv = found[0]
        scale = Scale(dev.address, epoch=epoch)
        try:
            await scale.connect()
            dump = await scale.dump(idle_timeout=idle_timeout)
        except (BleakError, asyncio.TimeoutError, OSError) as e:
            log.warning("session failed: %s", e)
            await scale.disconnect()
            await asyncio.sleep(reconnect_delay)
            continue
        await scale.disconnect()
        for r in dump.readings:
            if r.key not in seen:
                seen.add(r.key)
                yield r
