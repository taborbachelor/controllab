"""Full-line scenarios against Plant. These are the first "demonstrate
deterministic simulation" checks called for in docs/CONTROL-LAB.md §7 and
CLAUDE.md §24 — not yet the declarative scenario format from §12/§10 of
CLAUDE.md, which is Phase 3 (Testing) work.
"""
import pytest

from services.simulation.equipment.plant import Plant, PlantConfig

DT = 0.1


def run(plant: Plant, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        plant.step(DT)


def make_plant(**overrides) -> Plant:
    cfg = PlantConfig(
        bin_capacity_kg=10_000.0,
        bin_level_kg=1_000.0,
        gate_travel_time_s=1.0,
        feeder_max_rate_kg_s=5.0,
        feeder_start_delay_s=0.0,
        conveyor_length_m=4.0,
        conveyor_speed_m_s=2.0,  # 2.0s transit
        conveyor_start_delay_s=0.0,
        hopper_capacity_kg=2_000.0,
        hopper_draw_rate_kg_s=0.0,  # no downstream draw, for clean conservation checks
        **overrides,
    )
    return Plant(cfg)


def test_material_conservation_holds_through_a_full_run():
    plant = make_plant()
    starting_total = plant.total_mass_kg()

    plant.conveyor.command(True)
    plant.feeder.command(True, speed_pct=100.0)
    plant.gate.command(True)

    for _ in range(200):  # 20s simulated — plenty for gate + transit
        plant.step(DT)
        assert plant.accounted_mass_kg() == pytest.approx(starting_total)

    assert plant.hopper.level_kg > 0.0  # material actually arrived
    assert plant.spilled_kg == 0.0  # normal start order: nothing spilled


def test_normal_start_sequence_avoids_spillage():
    """Conveyor and gate before feeder — the correct commissioning order.
    docs/CONTROL-LAB.md §6.2's downstream-first sequence exists precisely
    to make this the outcome, even though Control (which enforces that
    order) isn't built yet — this test drives the sequence by hand."""
    plant = make_plant()

    plant.conveyor.command(True)
    run(plant, 0.2)
    assert plant.conveyor.motor.running

    plant.gate.command(True)
    run(plant, 1.2)
    assert plant.gate.is_open

    plant.feeder.command(True, speed_pct=100.0)
    run(plant, 3.0)

    assert plant.spilled_kg == 0.0
    assert plant.hopper.level_kg > 0.0


def test_feeding_onto_a_stopped_conveyor_spills():
    """The fault this project exists to catch: gate open, feeder running,
    conveyor never started."""
    plant = make_plant()
    plant.gate.command(True)
    run(plant, 1.2)
    assert plant.gate.is_open

    plant.feeder.command(True, speed_pct=100.0)
    run(plant, 2.0)  # conveyor never commanded

    assert plant.spilled_kg > 0.0
    assert plant.hopper.level_kg == 0.0


def test_estop_trips_all_motors_and_holds_until_reset():
    plant = make_plant()
    plant.conveyor.command(True)
    plant.feeder.command(True, speed_pct=100.0)
    plant.gate.command(True)
    run(plant, 1.5)
    assert plant.conveyor.motor.running

    plant.estop.trip()
    plant.step(DT)

    from services.simulation.equipment.motor import MotorState

    assert plant.conveyor.motor.state == MotorState.ESTOP
    assert plant.feeder.motor.state == MotorState.ESTOP

    # Commands re-asserted while tripped have no effect.
    plant.conveyor.command(True)
    plant.feeder.command(True, speed_pct=100.0)
    run(plant, 1.0)
    assert plant.conveyor.motor.state == MotorState.ESTOP
    assert plant.feeder.motor.state == MotorState.ESTOP

    # Releasing the E-stop alone is enough -- Plant.step() brings the
    # motors back to STOPPED automatically the moment estop.healthy is
    # true again (a real safety relay re-arms the starters on its own;
    # no separate estop_reset() call needed here).
    plant.estop.reset()
    run(plant, 0.1)
    assert plant.conveyor.motor.state == MotorState.STOPPED  # no auto-restart
    assert plant.feeder.motor.state == MotorState.STOPPED


def test_run_is_deterministic_across_repeated_runs():
    """Same inputs, same initial conditions -> identical results, every
    time (docs/CONTROL-LAB.md §7, item 3; CLAUDE.md §9)."""

    def run_scenario() -> tuple[float, float, float]:
        plant = make_plant()
        plant.conveyor.command(True)
        run(plant, 0.2)
        plant.gate.command(True)
        run(plant, 1.2)
        plant.feeder.command(True, speed_pct=73.0)
        run(plant, 4.0)
        return plant.hopper.level_kg, plant.spilled_kg, plant.bin.level_kg

    first = run_scenario()
    second = run_scenario()
    assert first == second
