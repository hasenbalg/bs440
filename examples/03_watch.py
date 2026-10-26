#!/usr/bin/env python3
"""React to every new weigh-in — the library form of `scalebridge watch`.

watch_scales() is an async generator that never returns: it waits for
advertisements (the scale wakes when stepped on), pulls the history
dump each time the scale wakes — the live weigh-in is always part of
that dump — and yields only readings it has never delivered before.

Deduplication is in-memory: a restart re-emits the stored history once.
Keep your own journal (set of (person, timestamp) keys, file, database)
if that matters to your pipeline.

Person slot 255 ("guest") = weigh-in the scale could not attribute to a
memory slot; body-comp values are absent there.

Run:  python 03_watch.py [AA:BB:CC:DD:EE:FF]
      (without an address: any scale in range)
"""
import asyncio
import sys

from scalebridge import watch_scales


async def main(address: str | None) -> None:
    async for r in watch_scales(address=address):
        if r.weight_kg is None:
            continue          # partial record; body arrived without weight
        print(f"{r.datetime}  slot={r.slot_name}  {r.weight_kg:.2f} kg"
              + (f"  fat {r.fat_pct:.1f}%" if r.fat_pct is not None else "")
              + (f"  bmi {r.bmi}" if r.bmi else ""))
        # ...from here: INSERT INTO your database of choice.


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
