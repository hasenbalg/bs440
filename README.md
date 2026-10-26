# scalebridge

Read a **Medisana BS440** body-composition scale over Bluetooth LE —
no vendor cloud, no Medisana app. Companion project to
[glucobridge](https://github.com/hasenbalg/gl49) (same shape: pure
decoders + bleak client + CLI), but for the bathroom instead of the
kitchen.

```bash
python3 -m venv .venv && .venv/bin/pip install -e .

.venv/bin/scalebridge scan                     # step on the scale first!
.venv/bin/scalebridge dump AA:BB:CC:DD:EE:FF --csv weight.csv
.venv/bin/scalebridge watch                    # one line per new weigh-in
.venv/bin/scalebridge info AA:BB:CC:DD:EE:FF   # GATT dump + firmware
```

`watch` is the long-running mode: it waits for advertisements (the
scale wakes when someone steps on), pulls the scale's stored history,
and prints only readings it has never delivered before — one line per
weigh-in, per person slot. Add `--json` for one JSON object per line,
pipe it anywhere.

Requires Python ≥ 3.10, BlueZ, and a BLE adapter (any Pi Zero W and up).
Only runtime dependency: [`bleak`](https://github.com/hbldh/bleak).

**Unpair the scale from the Medisana app / phone first.** Like most
scales it serves one central at a time.

## How the protocol works

The scale's private GATT service advertises as **`0x78B2`** and carries
four characteristics (16-bit UUIDs in the Bluetooth base form):

| UUID `0000xxxx-…` | dir | content |
|---|---|---|
| `8A81` | write | command register: `0x02 + scale_time` (u32 LE) → RTC sync **and** history dump |
| `8A82` | indicate | person profile: `0x84`, person 1–8, gender, age, height, activity |
| `8A21` | indicate | weight: `0x1d`, kg×100 (u16 LE), timestamp, person |
| `8A22` | indicate | body comp: `0x6f`, timestamp, person, kcal, fat/water/muscle/bone % (×10, high nibble `0xF`) |

Records are little-endian; the fixed first byte is the validity check.
A weight and its body record for one weigh-in share `(person,
timestamp)` — that's the merge key. The scale stores the last ~30
measurements per person slot and dumps them all when you write the
timestamp command, so **the history dump always includes the weigh-in
that just happened** — which is what makes `watch` a simple
dump-and-dedupe loop.

Identifying a BS440: most units advertise a **hex token, not a model
name** (e.g. Frank's BS440 advertises `0203B6ABC8A438C1A4`). Reliable
signals are the advertised `78B2` service or the name prefixes
`013197`/`013198`/`0202B6`/`0203B`; if in doubt, `scalebridge hunt`
connects to nearby devices and finds the one exposing the four
characteristics above.

Timestamps: some firmware counts from 2010-01-01 instead of Unix epoch.
`--epoch auto` (default) picks whichever interpretation lands within
±90 days of now, or force `--epoch 2010` / `unix`. Name prefixes
`013197`/`013198`/`0202B6` indicate 2010-based firmware; `0203B` is
plain Unix.

Person slot **255 = guest**: weigh-ins the scale couldn't attribute to
a memory slot (and empty slots in the profile dump) come back as
person `0xFF` with no body-comp values and no profile — real firmware
behavior, shown as `guest` by this client.

Byte layout as reverse-engineered by **keptenkurk** (see credits); the
unit tests pin the decoders to real captured packets from that writeup
(`tests/test_decode.py`).

## Testing on your own scale

```bash
.venv/bin/scalebridge hunt           # find + identify the scale by GATT
.venv/bin/scalebridge info <MAC>     # GATT map + what the dump looks like
.venv/bin/scalebridge dump <MAC>     # should print stored history
python3 tools/raw_capture.py <MAC>   # raw hex of every PDU, for debugging
```

If your unit sends records the decoder rejects, `raw_capture.py` prints
the exact bytes — open an issue with the hex and we'll add a dialect.

## Related work (where the protocol knowledge comes from)

This is an independent implementation, written from scratch for bleak +
asyncio with a clean decode/transport/test split. The **wire protocol
was reverse-engineered by others**, with credit where it's due:

* [keptenkurk/BS440](https://github.com/keptenkurk/BS440) and the
  accompanying blog series
  ([part 3](https://keptenkurk.wordpress.com/2016-03-26/connecting-the-medisana-bs440-bluetooth-scale-part-3))
  — the original decode of the `0x8A21/8A22/8A82` records, the
  timestamp-command history trigger, and the 2010-epoch model quirk.
  The golden test packets in `tests/` are from that writeup.
* [jinnerbichler/BS440](https://github.com/jinnerbichler/BS440) — MQTT
  plugin fork of the above; popularised the per-person MQTT topics.
* Home Assistant community threads on integrating the BS440
  ([example](https://community.home-assistant.io/t/integrating-the-medisana-bs440-bluetooth-enabled-bathroom-scale/24652)).
* [oliexdev/openScale](https://github.com/oliexdev/openScale) — Android
  app with a production BS44x driver (`MedisanaBs44xHandler`); source of
  the `78B2` service UUID, the hex-token advertisement-name mapping, and
  the ±90-days timestamp-epoch heuristic used here. Frank has used it
  with this exact scale for years — it's also what finally identified
  his unit in a noisy RF environment.
* The ESPHome port for the BS444 sibling,
  [bwynants/weegschaal](https://github.com/bwynants/weegschaal), for
  the same scale on an ESP32 instead of a Pi.

None of their code is copied here; the decode tables are re-derived
from their published protocol descriptions and pinned by tests against
their sample captures.

## License

MIT
