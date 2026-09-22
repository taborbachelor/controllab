"""Shared error type + tag-binding validation for the Control layer.

Control-layer modules bind to I/O image tags by name at construction
time. Validating each tag's direction and type immediately, rather than
failing later on first read/write, catches a wiring mistake (wrong tag
name, wrong direction) at startup instead of partway through a scenario.
"""
from __future__ import annotations

from services.simulation.engine.io_image import IOImage, TagType


class ControlError(Exception):
    """Raised on a Control-layer configuration or usage error — e.g. a
    device control module bound to a tag of the wrong type, or a command
    issued against a capability that wasn't configured (no speed tag)."""


def require_tag_type(io: IOImage, name: str, expected: TagType) -> None:
    actual = io.tag(name).type
    if actual != expected:
        raise ControlError(f"{name} is {actual.name}, expected {expected.name}")
