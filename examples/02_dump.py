#!/usr/bin/env python3
"""Pull the scale's stored history (up to ~30 measurements per person).

Connecting alone gets you nothing: the history flushes only after you
write 0x02 + current-time to the command characteristic 0x8A81, which
syncs the scale's RTC and triggers the dump.  Scale.dump() wraps the
whole session — subscribe, trigger, collect until the indication stream
goes quiet — and returns a Dump:

    dump.persons    list[Person]   profiles from the 8 memory slots
                                   (unoccupied slots are filtered)
    dump.readings   list[Reading]  weight merged with body-comp by
                                   (person, timestamp); .profile and
                                   .bmi populated where a profile exists

The scale serves one central at a time: unpair it from the Medisana app
first.

Run:  python 02_dump.py AA:BB:CC:DD:EE:FF
"""
import asyncio
import sys

from scalebridge import Scale


async def main(address: str) -> None:
    async with Scale(address) as scale:      # connect + disconnect
        dump = await scale.dump()

    for p in dump.persons:
        print(f"person {p.person}: {p.gender}, {p.age}y, "
              f"{p.size_cm}cm, activity={p.activity}")
    for r in dump.readings:
        print(r)                              # one human-readable line
        # r.weight_kg, r.fat_pct, r.tbw_pct, r.muscle_pct, r.bone_pct,
        # r.kcal, r.bmi, r.datetime, r.slot_name ("guest" or "1".."8"),
        # r.profile — or dict(r.to_dict()) for everything at once.
    print(f"-- {len(dump.readings)} readings")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
