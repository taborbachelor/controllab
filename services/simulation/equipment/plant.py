"""The bulk-material handling line: BIN-101 -> XV-102 -> FDR-103 -> CV-104 -> HOP-105.

Wires the five devices together and moves material between them each tick.
This is the whole "virtual plant" for Phase 1 (docs/CONTROL-LAB.md §5).

Material conservation is a first-class invariant: everything still in the
system plus everything that has left it (downstream draw or spillage) must
equal the starting total, at every tick (docs/CONTROL-LAB.md §7, item 6).
"""
from __future__ import annotations

from dataclasses import dataclass

from services.simulation.equipment.conveyor import Conveyor
from services.simulation.equipment.estop import EStop
from services.simulation.equipment.feeder import Feeder
from services.simulation.equipment.gate import Gate
from services.simulation.equipment.vessel import Hopper, MaterialBin


@dataclass
class PlantConfig:
    bin_capacity_kg: float = 10_000.0
    bin_level_kg: float | None = None
    bin_low_pct: float = 10.0

    gate_travel_time_s: float = 2.0

    feeder_max_rate_kg_s: float = 5.0
    feeder_start_delay_s: float = 0.5

    conveyor_length_m: float = 20.0
    conveyor_speed_m_s: float = 2.0
    conveyor_start_delay_s: float = 1.0

    hopper_capacity_kg: float = 2_000.0
    hopper_draw_rate_kg_s: float = 3.0
    hopper_high_pct: float = 80.0
    hopper_high_high_pct: float = 95.0


class Plant:
    """The virtual bulk-material line: five devices plus a plant-wide E-stop."""

    def __init__(self, config: PlantConfig | None = None) -> None:
        cfg = config or PlantConfig()
        self.bin = MaterialBin("BIN-101", cfg.bin_capacity_kg, cfg.bin_level_kg, cfg.bin_low_pct)
        self.gate = Gate("XV-102", cfg.gate_travel_time_s)
        self.feeder = Feeder("FDR-103", cfg.feeder_max_rate_kg_s, cfg.feeder_start_delay_s)
        self.conveyor = Conveyor(
            "CV-104", cfg.conveyor_length_m, cfg.conveyor_speed_m_s, cfg.conveyor_start_delay_s
        )
        self.hopper = Hopper(
            "HOP-105",
            cfg.hopper_capacity_kg,
            draw_rate_kg_s=cfg.hopper_draw_rate_kg_s,
            high_pct=cfg.hopper_high_pct,
            high_high_pct=cfg.hopper_high_high_pct,
        )
        self.estop = EStop()

        self.spilled_kg = 0.0
        self.time_s = 0.0

    def total_mass_kg(self) -> float:
        """Material still in the system right now (bin + belt + hopper)."""
        return self.bin.level_kg + self.conveyor.mass_on_belt_kg + self.hopper.level_kg

    def accounted_mass_kg(self) -> float:
        """total_mass_kg() plus everything that has left the system, in
        either direction. Should equal the plant's starting total at
        every tick — the conservation invariant (docs/CONTROL-LAB.md §7)."""
        return self.total_mass_kg() + self.hopper.total_discharged_kg + self.spilled_kg

    def step(self, dt: float) -> None:
        self.time_s += dt

        if self.estop.tripped:
            # A real E-stop removes power regardless of what's commanded.
            self.feeder.motor.run_command = False
            self.conveyor.motor.run_command = False
            self.gate.open_command = False
            self.feeder.motor.estop()
            self.conveyor.motor.estop()

        # Feeder discharges from the bin onto the belt, gated by the slide
        # gate. Gate/feeder state used here is start-of-scan (this tick's
        # commands land in gate.step()/feeder.step() below), matching the
        # scan-cycle model in docs/CONTROL-LAB.md §3.3.
        self.feeder.step(dt)
        offered = 0.0
        if self.gate.is_open and self.feeder.motor.running:
            offered = self.bin.discharge(self.feeder.current_rate_kg_s() * dt)
        self.gate.step(dt)

        self.spilled_kg += self.conveyor.load(offered)

        delivered = self.conveyor.step(dt)
        self.spilled_kg += self.hopper.receive(delivered)

        self.hopper.step(dt)
