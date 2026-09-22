"""The I/O image: a shared tag table between Simulation and Control.

This is the one hard boundary in the architecture (docs/CONTROL-LAB.md
§3.2): Control may only ever observe and command Simulation through this
table, never by touching simulation objects directly. The boundary is
enforced here, not just documented — the *direction* encoded in each
tag's type determines who is allowed to write it, the same way it does
in a real I/O table:

- **DI / AI** ("input", to the controller): the field device asserts it —
  here, Simulation — and Control reads it.
- **DO / AO** ("output", from the controller): Control asserts it, and
  the field device — Simulation — reads it to know what's commanded.

Both sides may always *read* any tag; only the write direction is
restricted. That mirrors real hardware too: Simulation has to read DO/AO
to know what's commanded, and Control has to read DI/AI to know what's
happening.

Every tag must be defined up front — a real I/O table has a fixed point
list, and reads/writes against anything else are a bug, not a feature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Union

TagValue = Union[bool, float]


class TagType(Enum):
    DI = auto()  # discrete input:  Simulation writes, Control reads
    DO = auto()  # discrete output: Control writes, Simulation reads
    AI = auto()  # analog input:    Simulation writes, Control reads
    AO = auto()  # analog output:   Control writes, Simulation reads

    @property
    def is_discrete(self) -> bool:
        return self in (TagType.DI, TagType.DO)

    @property
    def is_input(self) -> bool:
        """"Input" from the controller's point of view — Simulation writes it."""
        return self in (TagType.DI, TagType.AI)


@dataclass
class Tag:
    name: str
    type: TagType
    units: str = ""
    description: str = ""
    value: TagValue = field(default=False)

    def __post_init__(self) -> None:
        # Default value matches the tag's type if none was given.
        if self.type.is_discrete and not isinstance(self.value, bool):
            self.value = False
        if not self.type.is_discrete and isinstance(self.value, bool):
            self.value = 0.0


class IOImageError(Exception):
    """Raised on any I/O image contract violation: an undefined tag, a
    wrong-direction write, or a value of the wrong type. Deliberately a
    distinct exception — a violation here means the Simulation/Control
    boundary was crossed wrong, not an ordinary bug."""


class IOImage:
    """A flat table of named tags."""

    def __init__(self) -> None:
        self._tags: dict[str, Tag] = {}

    def define(
        self,
        name: str,
        type: TagType,
        units: str = "",
        description: str = "",
        initial: TagValue | None = None,
    ) -> None:
        if name in self._tags:
            raise IOImageError(f"tag already defined: {name}")
        tag = Tag(name=name, type=type, units=units, description=description)
        if initial is not None:
            self._set_validated(tag, initial)
        self._tags[name] = tag

    def _get(self, name: str) -> Tag:
        try:
            return self._tags[name]
        except KeyError:
            raise IOImageError(f"undefined tag: {name}") from None

    def read(self, name: str) -> TagValue:
        """Either side may read any tag."""
        return self._get(name).value

    def write_input(self, name: str, value: TagValue) -> None:
        """Simulation calls this to publish a DI/AI tag."""
        tag = self._get(name)
        if not tag.type.is_input:
            raise IOImageError(
                f"{name} is {tag.type.name}, an output — Simulation may only "
                "write_input() on DI/AI tags; Control writes outputs"
            )
        self._set_validated(tag, value)

    def write_output(self, name: str, value: TagValue) -> None:
        """Control calls this to issue a DO/AO command."""
        tag = self._get(name)
        if tag.type.is_input:
            raise IOImageError(
                f"{name} is {tag.type.name}, an input — Control may only "
                "write_output() on DO/AO tags; Simulation writes inputs"
            )
        self._set_validated(tag, value)

    @staticmethod
    def _set_validated(tag: Tag, value: TagValue) -> None:
        # bool is a subclass of int in Python, so the analog check has to
        # reject it explicitly rather than rely on isinstance(value, float).
        if tag.type.is_discrete:
            if not isinstance(value, bool):
                raise IOImageError(
                    f"{tag.name} is {tag.type.name} (discrete) — expected "
                    f"bool, got {type(value).__name__}"
                )
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise IOImageError(
                    f"{tag.name} is {tag.type.name} (analog) — expected a "
                    f"number, got {type(value).__name__}"
                )
        tag.value = bool(value) if tag.type.is_discrete else float(value)

    def tag(self, name: str) -> Tag:
        """The full Tag record (type, units, description, value) — for
        introspection, reports, or a future protocol adapter."""
        return self._get(name)

    def names(self) -> list[str]:
        return list(self._tags.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tags

    def __len__(self) -> int:
        return len(self._tags)
