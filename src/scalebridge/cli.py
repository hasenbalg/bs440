"""Command-line interface: scalebridge scan|dump|watch|info."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys

from bleak.exc import BleakError

from .client import Scale, _short_uuids, find_scales, match_reason, watch_scales
from .decode import EPOCH_MODES
from .models import Reading


def _emit(readings: list[Reading], args) -> None:
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(Reading.CSV_HEADER)
            for r in readings:
                w.writerow(r.to_csv_row())
        print(f"wrote {len(readings)} readings to {args.csv}")
    elif args.json:
        json.dump([r.to_dict() for r in readings], sys.stdout, indent=1)
        print()
    else:
        for r in readings:
            print(r)
        print(f"-- {len(readings)} readings")


async def cmd_scan(args):
    devices = await find_scales(timeout=args.timeout)
    for dev, adv in devices:
        name = dev.name or getattr(adv, "local_name", None) or "(unnamed)"
        via = match_reason(dev, adv) if adv else "address"
        svcs = _short_uuids(adv) if adv else ""
        print(f"{dev.address}  {name:<20} rssi={getattr(adv, 'rssi', None)}"
              f"  via={via}  svcs=[{svcs}]")
    if not devices:
        print("no scales found (step on the scale so it wakes up)")


async def cmd_dump(args):
    async with Scale(args.address, epoch=args.epoch) as scale:
        dump = await scale.dump(idle_timeout=args.idle, max_time=args.max)
    for p in dump.persons:
        print(f"person {p.person}: {p.gender}, {p.age}y, {p.size_cm}cm, "
              f"activity={p.activity}", file=sys.stderr)
    if not dump.readings:
        print("0 readings.  Make sure the scale is awake (step on it), "
              "unpaired from any phone app, and try --max 60.",
              file=sys.stderr)
    _emit(dump.readings, args)


async def cmd_watch(args):
    try:
        async for r in watch_scales(address=args.address or None,
                                    epoch=args.epoch,
                                    idle_timeout=args.idle):
            if args.json:
                print(json.dumps(r.to_dict()), flush=True)
            else:
                print(r, flush=True)
    except KeyboardInterrupt:
        pass


async def cmd_info(args):
    async with Scale(args.address) as scale:
        print("characteristics:")
        for service in scale.services:
            for char in service.characteristics:
                marks = "".join(
                    c for c, prop in (("r", "read"), ("w", "write"),
                                      ("W", "write-without-response"),
                                      ("n", "notify"), ("I", "indicate"))
                    if prop in char.properties)
                print(f"  {char.uuid}  [{marks}]")
        info = await scale.device_info()
        for k, v in info.items():
            print(f"{k}: {v}")
        print("\ntriggering a history dump ...")
        await scale.subscribe()
        await scale.sync_clock()
        await scale.collect(idle_timeout=args.idle)
        dump = scale.result()
    print(f"{len(dump.persons)} person profiles, "
          f"{len(dump.readings)} readings")
    for uuid, data in scale.unhandled:
        print(f"unhandled indication {uuid}: {data.hex()}")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="scalebridge",
        description="Read Medisana BS440-family body scales over BLE "
                    "(no vendor cloud).")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="find scales (step on the scale first)")
    p.add_argument("--timeout", type=float, default=10.0)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("dump", help="pull the scale's stored history")
    p.add_argument("address")
    p.add_argument("--epoch", choices=EPOCH_MODES, default="auto",
                   help="timestamp epoch: auto (default), unix, or 2010 "
                        "(BS410/BS444 firmware)")
    p.add_argument("--idle", type=float, default=6.0,
                   help="finish after this many seconds of silence")
    p.add_argument("--max", type=float, default=60.0,
                   help="hard time limit for the dump")
    p.add_argument("--csv", metavar="FILE")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("watch", help="emit each new weigh-in, forever")
    p.add_argument("address", nargs="?",
                   help="scale MAC (default: any scale in range)")
    p.add_argument("--epoch", choices=EPOCH_MODES, default="auto")
    p.add_argument("--idle", type=float, default=6.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("info", help="GATT + firmware info (diagnostics)")
    p.add_argument("address")
    p.add_argument("--idle", type=float, default=6.0)
    p.set_defaults(func=cmd_info)

    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S")
    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        pass
    except (OSError, BleakError) as e:
        # No BlueZ / no adapter / scale vanished mid-session.
        sys.exit(f"Bluetooth error: {e}\n"
                 "Is bluetoothd running and an adapter up "
                 "(rfkill list; systemctl status bluetooth)?")


if __name__ == "__main__":
    main()
