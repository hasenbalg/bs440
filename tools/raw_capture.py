#!/usr/bin/env python3
"""Raw indication capture for protocol debugging.

Connects to the scale, subscribes to every characteristic that can
indicate/notify (by property, not by known UUID), triggers the history
dump, and prints every PDU as `uuid  hex`.  No decoding -- use this on
a Pi when a scale/firmware surprises the decoder, then file the hex.

Usage:  python tools/raw_capture.py AA:BB:CC:DD:EE:FF [seconds]
"""
import asyncio
import sys
import time

from bleak import BleakClient


async def main(address: str, seconds: int) -> None:
    async with BleakClient(address, timeout=30) as client:
        interesting = []
        print("== services ==")
        for service in client.services:
            print(f"service {service.uuid}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"  char {char.uuid}  [{props}]")
                if {"indicate", "notify"} & set(char.properties):
                    interesting.append(char)

        def on_pdu(char, data: bytearray):
            print(f"IN {char.uuid}  {bytes(data).hex()}", flush=True)

        for char in interesting:
            await client.start_notify(char, on_pdu)
            print(f"subscribed {char.uuid}")

        cmd = client.services.get_characteristic(
            "00008a81-0000-1000-8000-00805f9b34fb")
        if cmd:
            payload = b"\x02" + int(time.time()).to_bytes(4, "little")
            print(f"OUT {cmd.uuid}  {payload.hex()}")
            try:
                await asyncio.wait_for(
                    client.write_gatt_char(
                        cmd, payload, response="write" in cmd.properties),
                    timeout=5)
            except Exception as e:
                print(f"(write did not complete: {e})")

        await asyncio.sleep(seconds)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2
                     else 30))
