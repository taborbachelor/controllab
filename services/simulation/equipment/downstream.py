"""DS-107: the downstream process the hopper feeds -- a minimal consumer.

The hopper is a buffer between an upstream source (the bins, feeder and
conveyor) and this downstream consumer (docs/CONTROL-LAB.md §5.1). The
consumer takes material through the hopper's open outlet at its own rate,
but only while it is accepting it; when it isn't (stopped, full, down for
its own reasons), nothing leaves the hopper even with the outlet open --
the discharge chute simply backs up. It tells the line which it is with
one fail-safe signal, DS-107.READY (1 = ready), and the line's controller
decides whether to open the outlet from that; this model decides nothing.

Deliberately minimal: no internal process, no rate changes, no dynamics.
Its rate is the plant's hopper_draw_rate_kg_s.
"""
from __future__ import annotations


class DownstreamConsumer:
    def __init__(self, name: str = "DS-107") -> None:
        self.name = name
        # Process condition, injectable: the downstream process has stopped
        # taking material. Ready is simply "not stopped".
        self.stopped = False

    @property
    def ready(self) -> bool:
        return not self.stopped
