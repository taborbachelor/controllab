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
from services.simulation.equipment.instruments import Instruments
from services.simulation.equipment.vessel import Hopper, MaterialBin


@dataclass
class PlantConfig:
    bin_capacity_kg: float = 10_000.0
    bin_level_kg: float | None = None
    bin_low_pct: float = 10.0

    gate_travel_time_s: float = 2.0

    feeder_max_rate_kg_s: float = 5.0
    feeder_start_delay_s: float = 0.5
    feeder_plug_detect_s: float = 2.0  # running against a jam until LSH-103 makes

    conveyor_length_m: float = 20.0
    conveyor_speed_m_s: float = 2.0
    conveyor_start_delay_s: float = 1.0
    conveyor_full_load_a: float = 12.0  # the motor's nameplate full-load current
    conveyor_jam_overload_s: float = 5.0  # its overload relay's trip time at jam current

    hopper_capacity_kg: float = 2_000.0
    hopper_draw_rate_kg_s: float = 3.0
    hopper_high_pct: float = 80.0
    hopper_high_high_pct: float = 95.0

    instrument_seed: int = 0  # the root of every instrument noise stream (instruments.py)


class Plant:
    """The virtual bulk-material line: five devices plus a plant-wide E-stop."""

    def __init__(self, config: PlantConfig | None = None) -> None:
        cfg = config or PlantConfig()
        self.bin = MaterialBin("BIN-101", cfg.bin_capacity_kg, cfg.bin_level_kg, cfg.bin_low_pct)
        self.gate = Gate("XV-102", cfg.gate_travel_time_s)
        self.feeder = Feeder("FDR-103", cfg.feeder_max_rate_kg_s, cfg.feeder_start_delay_s, cfg.feeder_plug_detect_s)
        self.conveyor = Conveyor(
            "CV-104", cfg.conveyor_length_m, cfg.conveyor_speed_m_s, cfg.conveyor_start_delay_s,
            full_load_a=cfg.conveyor_full_load_a,
            # Rated belt load: the feeder's full rate for one belt transit.
            rated_load_kg=cfg.feeder_max_rate_kg_s * cfg.conveyor_length_m / cfg.conveyor_speed_m_s,
            jam_overload_s=cfg.conveyor_jam_overload_s,
        )
        self.hopper = Hopper(
            "HOP-105",
            cfg.hopper_capacity_kg,
            draw_rate_kg_s=cfg.hopper_draw_rate_kg_s,
            high_pct=cfg.hopper_high_pct,
            high_high_pct=cfg.hopper_high_high_pct,
        )
        self.estop = EStop()
        # What the field instruments report, including injected sensor
        # faults (instruments.py). WT-105's input channel has a fault
        # diagnostic; no other instrument's does.
        self.instruments = Instruments(
            diagnosed={"WT-105"},
            # Calibrated ranges: the bin's level transmitter in %, the hopper's
            # load cells over the hopper's capacity (as the Modbus map spans them).
            ranges={"LT-101": (0.0, 100.0), "WT-105": (0.0, cfg.hopper_capacity_kg),
                    "IT-104": (0.0, 100.0), "FT-104": (0.0, 10.0)},
            seed=cfg.instrument_seed,
        )

        self.spilled_kg = 0.0
        self.time_s = 0.0
        # What the belt scale at the conveyor head measures (FT-104), kg/s.
        self.belt_flow_kg_s = 0.0
        # What actually left the bin through the feeder this tick, kg/s: less
        # than the feeder's rate when the bin runs empty, zero when it bridges.
        self.feed_flow_kg_s = 0.0

    def total_mass_kg(self) -> float:
        """Material still in the system right now (bin + belt + hopper)."""
        return self.bin.level_kg + self.conveyor.mass_on_belt_kg + self.hopper.level_kg

    def accounted_mass_kg(self) -> float:
        """total_mass_kg() plus everything that has left the system, in
        either direction. Should equal the plant's starting total at
        every tick — the conservation invariant (docs/CONTROL-LAB.md §7)."""
        return self.total_mass_kg() + self.hopper.total_discharged_kg + self.spilled_kg

    def step(self, dt: float) -> None:
        # Rounded like SimClock and the Motor/Gate timers (Phase 1): a
        # bare += dt drifts (25 x 0.1 -> 2.500000000000001), and every
        # telemetry timestamp is read from here.
        self.time_s = round(self.time_s + dt, 9)
        self.instruments.now = self.time_s

        if self.estop.tripped:
            # A real E-stop removes power regardless of what's commanded.
            self.feeder.motor.run_command = False
            self.conveyor.motor.run_command = False
            self.gate.open_command = False
            self.feeder.motor.estop()
            self.conveyor.motor.estop()
        else:
            # A real E-stop's safety relay re-arms the motor starters the
            # instant the button releases -- automatically, at the
            # hardware level, independent of whatever Control does or
            # doesn't do. estop_reset() only leaves ESTOP for STOPPED
            # (never restarts anything -- a run command is still
            # required) and no-ops if the motor isn't in ESTOP, so this
            # is safe to call unconditionally every tick. Control-layer
            # code (services/control/) can't do this itself: it's a raw
            # simulation-object call, and Control may only ever touch
            # Simulation through the I/O image (docs/CONTROL-LAB.md
            # §3.2) -- see LineController's ESTOPPED handling for the
            # other half of this: continuously holding every command at
            # False so a stale one can't exploit the motor becoming
            # available again to restart it on its own.
            self.feeder.motor.estop_reset()
            self.conveyor.motor.estop_reset()

        # Feeder discharges from the bin onto the belt, gated by the slide
        # gate. Gate/feeder state used here is start-of-scan (this tick's
        # commands land in gate.step()/feeder.step() below), matching the
        # scan-cycle model in docs/CONTROL-LAB.md §3.3.
        self.feeder.step(dt)
        offered = 0.0
        if self.gate.is_open and self.feeder.motor.running:
            offered = self.bin.discharge(self.feeder.current_rate_kg_s() * dt)
        self.gate.step(dt)
        self.feed_flow_kg_s = offered / dt if dt > 0 else 0.0

        self.spilled_kg += self.conveyor.load(offered)

        delivered = self.conveyor.step(dt)
        self.belt_flow_kg_s = delivered / dt if dt > 0 else 0.0
        self.spilled_kg += self.hopper.receive(delivered)

        self.hopper.step(dt)
