# scalebridge examples

Small, runnable, no side effects beyond reading the scale.
Install the package first (`pip install -e .`), then:

| Script | What it shows |
|---|---|
| `01_scan.py` | finding the scale (advertisements, name/service matching) |
| `02_dump.py` | one full history-dump session → `Dump` objects |
| `03_watch.py` | live weigh-ins as an async generator |

The scripts mirror the CLI commands (`scan`, `dump`, `watch`) but use
the library API directly — pick whichever layer fits your project.
