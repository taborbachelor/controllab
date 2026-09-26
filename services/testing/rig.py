"""Builds the canonical Control-driven test rig: a fresh Plant wired to
the I/O image, the three device-control modules, and a LineController on
top -- the exact stack Phase 2 already proved out.

Centralized here (services/testing/, not tests/) because Phase 3's
scenario runner needs the same rig the ordinary pytest suite already
builds by hand in tests/integration/test_line_controller.py. Two
independent "canonical rig" definitions would drift; one shared builder
can't.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.control.gate_control import GateControl
from services.control.line_controller import LineController
from services.control.motor_control import MotorControl
from services.simulation.engine.io_image import IOImage
from services.simulation.engine.plant_io import build_line_io_image, publish_plant_inputs
from services.simulation.engine.plant_io import scan as plant_scan
from services.simulation.equipment.plant import Plant, PlantConfig

DT = 0.1

# The line's physical parameters, held fast for every Control-driven test
# and scenario. Proof windows are deliberately short (vs. the §6.2
# defaults of 3s/5s/15s) so tests run in milliseconds without changing
# what's being proved -- only how long healthy equipment takes to prove
# it.
DEFAULT_PLANT_CONFIG = dict(
    bin_capacity_kg=10_000.0,
    bin_level_kg=2_000.0,  # 20% -- comfortably above the 10% low threshold
    bin_b_level_kg=2_000.0,
    bin_c_level_kg=2_000.0,
    bin_low_pct=10.0,
    gate_travel_time_s=1.0,
    feeder_max_rate_kg_s=5.0,
    feeder_start_delay_s=0.2,
    feeder_plug_detect_s=0.5,
    conveyor_length_m=4.0,
    conveyor_speed_m_s=2.0,
    conveyor_start_delay_s=0.2,
    hopper_capacity_kg=2_000.0,
    # The downstream consumer's rate (DS-107), through the hopper's outlet:
    # below the feed rate, as on a real buffered line (and the plant default,
    # 3 kg/s against 5), so in Auto the hopper fills, holds at the high switch
    # and cycles 60 %/80 % behind the draw. It was 10 kg/s while only a batch
    # discharge opened the outlet; with Auto discharging, that outran the feed
    # and the hopper could never fill.
    hopper_draw_rate_kg_s=3.0,
    hopper_high_pct=80.0,
    hopper_high_high_pct=95.0,
)

DEFAULT_LINE_CONFIG = dict(
    feed_speed_pct=100.0,
    restart_below_pct=60.0,
    conveyor_proof_timeout_s=1.0,
    purge_time_s=2.0,  # real default is 15.0 -- shortened so tests run fast
    no_flow_s=4.0,  # a belt transit (2 s here) plus margin; real default 15.0
    # Batch commissioning for this rig: the belt carries 5 kg/s x 2 s = 10 kg
    # in flight; empty is 2 kg; the discharge timeout must exceed the largest
    # batch's discharge (1,600 kg under the high switch at 10 kg/s = 160 s).
    # It was 120 s, and a 1,200 kg batch timed out: found by the accuracy test.
    batch_preact_kg=10.0,
    batch_empty_kg=2.0,
    batch_tolerance_kg=5.0,
    discharge_timeout_s=600.0,  # the largest recipe (1,600 kg) takes 533 s at the 3 kg/s draw; real default 900
)

DEFAULT_DEVICE_PROOF_TIMEOUT_S = 1.0
DEFAULT_GATE_TRAVEL_TIMEOUT_S = 2.0


@dataclass
class Rig:
    plant: Plant
    io: IOImage
    # None in external-controller mode (Phase 7 step 3): the plant runs
    # with no built-in controller and something outside ControlLab writes
    # the outputs over Modbus. tick() then only advances the plant.
    line: LineController | None


def build_rig(
    plant_overrides: dict | None = None,
    line_overrides: dict | None = None,
    with_controller: bool = True,
    line_cls: type[LineController] = LineController,
) -> Rig:
    """`line_cls`: the controller class to build. Always LineController except
    for the deliberate-regression fixtures (services/testing/regressions.py)."""
    plant_cfg = dict(DEFAULT_PLANT_CONFIG)
    plant_cfg.update(plant_overrides or {})
    cfg = PlantConfig(**plant_cfg)

    plant = Plant(cfg)
    io = build_line_io_image()
    publish_plant_inputs(plant, io)

    line = build_line_controller(io, cfg.hopper_capacity_kg, line_overrides, line_cls) if with_controller else None
    return Rig(plant=plant, io=io, line=line)


def build_line_controller(
    io: IOImage,
    hopper_capacity_kg: float,
    line_overrides: dict | None = None,
    line_cls: type[LineController] = LineController,
) -> LineController:
    """The canonical controller stack (three device-control modules + the
    line state machine) on a given I/O image -- split out of build_rig()
    so the reference external controller (services/protocols/
    external_controller.py) runs *exactly* the controller every scenario
    and test runs, just against an I/O image mirrored over Modbus instead
    of one shared with a Plant."""
    feeder_ctrl = MotorControl(
        io,
        "M-103.RUN",
        "M-103.RUNNING",
        "M-103.FAULT",
        speed_tag="SC-103",
        start_proof_timeout_s=DEFAULT_DEVICE_PROOF_TIMEOUT_S,
    )
    conveyor_ctrl = MotorControl(
        io, "M-104.RUN", "M-104.RUNNING", "M-104.OL", start_proof_timeout_s=DEFAULT_DEVICE_PROOF_TIMEOUT_S
    )
    gate_ctrl = GateControl(io, "XV-102.CMD_OPEN", "ZSO-102", "ZSC-102", travel_timeout_s=DEFAULT_GATE_TRAVEL_TIMEOUT_S)
    gate_b_ctrl = GateControl(io, "XV-112.CMD_OPEN", "ZSO-112", "ZSC-112", travel_timeout_s=DEFAULT_GATE_TRAVEL_TIMEOUT_S)
    gate_c_ctrl = GateControl(io, "XV-122.CMD_OPEN", "ZSO-122", "ZSC-122", travel_timeout_s=DEFAULT_GATE_TRAVEL_TIMEOUT_S)
    outlet_ctrl = GateControl(io, "XV-106.CMD_OPEN", "ZSO-106", "ZSC-106", travel_timeout_s=DEFAULT_GATE_TRAVEL_TIMEOUT_S)

    line_cfg = dict(DEFAULT_LINE_CONFIG)
    line_cfg.update(line_overrides or {})
    return line_cls(
        io,
        feeder_ctrl,
        conveyor_ctrl,
        gate_ctrl,
        hopper_capacity_kg=hopper_capacity_kg,
        gate_b_ctrl=gate_b_ctrl,
        gate_c_ctrl=gate_c_ctrl,
        outlet_ctrl=outlet_ctrl,
        **line_cfg,
    )


def tick(rig: Rig, dt: float = DT) -> None:
    if rig.line is not None:
        rig.line.scan(dt)
    plant_scan(rig.plant, rig.io, dt)


def run(rig: Rig, seconds: float, dt: float = DT) -> None:
    for _ in range(round(seconds / dt)):
        tick(rig, dt)
