"""Data model: person profiles and merged measurements."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

UTC = dt.timezone.utc

# Firmware reports unoccupied memory slots and unidentified weigh-ins
# (guest users) as person 255.
GUEST_SLOT = 0xFF


def _iso(ts: int) -> str:
    if not ts:
        return ""
    return dt.datetime.fromtimestamp(ts, tz=UTC).isoformat(sep=" ",
                                                           timespec="seconds")


@dataclass
class Person:
    """Profile stored in one of the scale's 8 memory slots."""
    person: int
    gender: str = ""
    age: int = 0
    size_cm: int = 0
    activity: str = ""

    def to_dict(self) -> dict:
        return {"person": self.person, "gender": self.gender,
                "age": self.age, "size_cm": self.size_cm,
                "activity": self.activity}


@dataclass
class Reading:
    """One measurement: weight merged with its body-composition record.

    Weight and body records of a single weigh-in share (person,
    timestamp), which is how the client merges them.
    """
    person: int
    timestamp: int
    weight_kg: Optional[float] = None
    kcal: Optional[int] = None
    fat_pct: Optional[float] = None
    tbw_pct: Optional[float] = None
    muscle_pct: Optional[float] = None
    bone_pct: Optional[float] = None
    profile: Optional[Person] = field(default=None, repr=False)

    @property
    def key(self) -> tuple:
        return (self.person, self.timestamp)

    @property
    def slot_name(self) -> str:
        return "guest" if self.person == GUEST_SLOT else str(self.person)

    @property
    def datetime(self) -> Optional[dt.datetime]:
        return dt.datetime.fromtimestamp(self.timestamp, tz=UTC) \
            if self.timestamp else None

    @property
    def bmi(self) -> Optional[float]:
        if self.weight_kg and self.profile and self.profile.size_cm:
            m = self.profile.size_cm / 100.0
            return round(self.weight_kg / (m * m), 1)
        return None

    def to_dict(self) -> dict:
        d = {"person": self.person, "slot": self.slot_name,
             "timestamp": self.timestamp,
             "datetime": _iso(self.timestamp), "weight_kg": self.weight_kg,
             "kcal": self.kcal, "fat_pct": self.fat_pct,
             "tbw_pct": self.tbw_pct, "muscle_pct": self.muscle_pct,
             "bone_pct": self.bone_pct, "bmi": self.bmi}
        if self.profile:
            d["profile"] = self.profile.to_dict()
        return d

    def _fmt(self, v, unit="", nd=1):
        return "  --  " if v is None else f"{v:.{nd}f}{unit}"

    def __str__(self) -> str:
        w = "  --  " if self.weight_kg is None else f"{self.weight_kg:.2f}kg"
        return (f"{_iso(self.timestamp)}  {self.slot_name:>5}  {w:>9}  "
                f"fat {self._fmt(self.fat_pct)}  "
                f"water {self._fmt(self.tbw_pct)}  "
                f"muscle {self._fmt(self.muscle_pct)}  "
                f"bone {self._fmt(self.bone_pct)}  "
                f"kcal {self.kcal if self.kcal is not None else '  --  '}")

    CSV_HEADER = ["datetime", "timestamp", "person", "weight_kg", "bmi",
                  "fat_pct", "tbw_pct", "muscle_pct", "bone_pct", "kcal",
                  "gender", "age", "size_cm", "activity"]

    def to_csv_row(self) -> list:
        p = self.profile
        return [_iso(self.timestamp), self.timestamp, self.person,
                self.weight_kg, self.bmi, self.fat_pct, self.tbw_pct,
                self.muscle_pct, self.bone_pct, self.kcal,
                p.gender if p else "", p.age if p else "",
                p.size_cm if p else "", p.activity if p else ""]


@dataclass
class Dump:
    """Everything one connection pulled off the scale."""
    persons: list[Person] = field(default_factory=list)
    readings: list[Reading] = field(default_factory=list)

    def attach_profiles(self) -> None:
        by_person = {p.person: p for p in self.persons}
        for r in self.readings:
            r.profile = by_person.get(r.person)
