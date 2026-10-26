#!/usr/bin/env python3
"""Find nearby BS440-family scales.

find_scales() listens for BLE advertisements and keeps anything whose
name matches the known Medisana patterns (many units advertise a hex
token like 0203B6ABC8A438C1A4, not "BS440") or which advertises the
private 78B2 scale service.  It returns (BLEDevice, AdvertisementData)
tuples -- no connections, safe to run anytime.

The scale sleeps between weigh-ins and advertises only while awake and
connected-to-nothing, so step on it while this runs if it finds
nothing.  (all_devices=True returns the whole RF environment instead,
what matched and why is shown via match_reason().)

Run:  python 01_scan.py
"""
import asyncio

from scalebridge import find_scales, match_reason


async def main() -> None:
    devices = await find_scales(timeout=15.0)

    if not devices:
        print("no scales found — step on it so it wakes up")

    for dev, adv in devices:
        name = dev.name or getattr(adv, "local_name", None) or "(unnamed)"
        print(f"{dev.address}  {name:<20} rssi={adv.rssi} "
              f"via={match_reason(dev, adv)}")
        # dev.address is what dump/watch below take.


asyncio.run(main())
