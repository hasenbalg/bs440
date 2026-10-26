"""GATT UUIDs used by the Medisana BS440 protocol family.

The scale exposes a private service with four characteristics; three of
them are *indicate*-only data channels (the indication value reports one
handle below the characteristic declaration) and one is a command
register.  Handles vary between firmware revisions, so everything here
is matched by UUID, never by handle.
"""
from __future__ import annotations

BASE = "0000{:04x}-0000-1000-8000-00805f9b34fb"


def uuid16(u: int) -> str:
    return BASE.format(u)


# Medisana/Chipsea private service
SCALE_SERVICE = uuid16(0x8080)          # seen in advertisements

# Data + command characteristics (all 16-bit, private range)
CHAR_COMMAND = uuid16(0x8A81)           # write: 0x02 + unix time (LE u32) -> RTC sync + history dump
CHAR_PERSON = uuid16(0x8A82)            # indicate: person profile record (magic 0x84)
CHAR_WEIGHT = uuid16(0x8A21)            # indicate: weight record (magic 0x1d)
CHAR_BODY = uuid16(0x8A22)              # indicate: body-composition record (magic 0x6f)

DATA_CHARS = (CHAR_PERSON, CHAR_WEIGHT, CHAR_BODY)

# Device Information Service (present on some firmware builds)
DEVICE_INFO_SERVICE = uuid16(0x180A)
MANUFACTURER_NAME = uuid16(0x2A29)
MODEL_NUMBER = uuid16(0x2A24)
FIRMWARE_REVISION = uuid16(0x2A26)

# Client Characteristic Configuration Descriptor
CCCD = uuid16(0x2902)
