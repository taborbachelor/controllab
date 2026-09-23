"""The real-time runner (Phase 9 step 1): the unchanged scenarios against
a FREE-RUNNING external controller, the plant paced on the wall clock.

The controller under test is ControlLab's reference controller in a
thread, running free on its own clock and reaching the plant only over
Modbus, so no PLC runtime is needed; examples/openplc covers a real one.
The plant runs at SPEED x real time, which is valid only because the
reference controller's timers count plant time per scan (a real PLC runs
at 1x). The full suite at 1x is a CLI run, not a unit test.
"""
import threading
from pathlib import Path

import pytest

from services.testing.realtime import RealtimePlant, ReferenceController, run_realtime
from services.testing.scenario import Scenario

REPO = Path(__file__).resolve().parents[2]
SPEED = 4.0


def scenario(rel):
    return Scenario.load(REPO / "scenarios" / rel)


@pytest.fixture
def rt():
    plant = RealtimePlant(port=0)
    controllers = []

    def controller(**kw):
        c = ReferenceController(plant.port, speed=SPEED, **kw)
        controllers.append(c)
        return c

    yield plant, controller
    for c in controllers:
        c.close()
    plant.close()


@pytest.mark.parametrize("rel", [
    "startup/normal_start.yaml",
    "faults/feeder_trip_while_running.yaml",
    "faults/bin_low_blocks_start.yaml",
    "safety/estop_from_running.yaml",
])
def test_scenarios_pass_unchanged_against_a_free_running_controller(rt, rel):
    plant, controller = rt
    result = run_realtime(scenario(rel), plant, controller(), speed=SPEED)
    assert result.passed, result.detail
    assert not result.within_tolerance  # a fast controller needs none of the allowance


def test_every_scenario_starts_from_a_clean_restarted_controller(rt):
    """A trip leaves the controller FAULTED with a latched alarm; the next
    scenario must still start from a clean IDLE, and the power-up
    procedure that got it there isn't part of the scenario's record."""
    plant, controller = rt
    ctl = controller()
    tripped = run_realtime(scenario("faults/feeder_trip_while_running.yaml"), plant, ctl, speed=SPEED)
    assert tripped.passed, tripped.detail

    refused = run_realtime(scenario("faults/bin_low_blocks_start.yaml"), plant, ctl, speed=SPEED)
    assert refused.passed, refused.detail  # IDLE + start_inhibit == BIN_LOW: not stale state
    commands = [e.data["command"] for e in refused.events if e.type == "command_issued"]
    assert commands == ["start"]


def test_a_slow_controller_is_judged_with_the_stated_tolerance(rt):
    """A 300 ms task cycle: the trip can't be seen, acted on, and published
    inside 0.1 s of plant time, so the result is met *within tolerance*,
    and says so, rather than passing as on time or failing outright."""
    plant, controller = rt
    tight = Scenario(
        name="trip with a limit tighter than one scan", path=Path("tight.yaml"),
        given={"line_state": "running"}, when={"feeder_trip": True},
        expect={"line_state": "faulted"}, within_s=0.1,
    )
    result = run_realtime(tight, plant, controller(scan_s=0.3), speed=SPEED, latency_s=0.5)
    assert result.passed and result.within_tolerance, result.detail
    assert "inside the 0.5s latency tolerance" in result.detail


class _NeverStarts:
    name = "a controller that isn't there"

    def restart(self):
        pass

    def close(self):
        pass


def test_a_controller_that_never_writes_is_reported_not_blamed_on_the_scenario(rt):
    plant, _ = rt
    result = run_realtime(scenario("startup/normal_start.yaml"), plant, _NeverStarts(), speed=SPEED, ready_timeout_s=0.5)
    assert not result.passed
    assert "never wrote its outputs" in result.detail


def test_a_controller_dying_mid_run_invalidates_the_run(rt):
    """The run stops at the silence with that reason -- not a timeout, and
    not a 30 s wait for a RUNNING that can never come."""
    plant, controller = rt
    ctl = controller()
    original_restart = ctl.restart

    def restart_then_die():
        original_restart()
        threading.Timer(0.3, ctl.close).start()

    ctl.restart = restart_then_die
    result = run_realtime(scenario("shutdown/normal_stop.yaml"), plant, ctl, speed=SPEED)
    assert not result.passed
    assert result.detail.startswith("run invalid, not a verdict on the logic: controller stopped writing")


def test_repeated_passes_give_a_spread_and_one_combined_verdict(rt):
    from services.testing.realtime import run_suite_realtime

    plant, controller = rt
    scenarios = [scenario("faults/feeder_trip_while_running.yaml"), scenario("faults/bin_low_blocks_start.yaml")]
    seen = []
    runs = run_suite_realtime(scenarios, plant, controller(), repeat=2, speed=SPEED,
                              on_result=lambda n, s, r: seen.append((n, s.name)))
    assert [n for n, _ in seen] == [1, 1, 2, 2]  # each pass completes before the next starts
    for entry in runs:
        assert len(entry.responses) == 2 and all(t is not None for t in entry.responses)
        combined = entry.combined()
        assert combined.passed and combined.elapsed_s == max(entry.responses)


def test_a_controller_without_a_status_block_is_judged_on_the_field_alone(rt):
    """Declared status-less: the power-up runs blind, observable
    expectations still decide, and a scenario that can only be judged
    from the controller's state is reported not observable."""
    plant, controller = rt
    ctl = controller()
    partial = run_realtime(scenario("safety/estop_from_running.yaml"), plant, ctl, speed=SPEED, status=False)
    assert partial.passed and partial.not_observed == ("line_state",), partial.detail
    blind = run_realtime(scenario("faults/bin_low_blocks_start.yaml"), plant, ctl, speed=SPEED, status=False)
    assert blind.not_observable and not blind.passed


def test_the_same_logic_passes_at_relocated_addresses(rt_relocated):
    """Phase 9 step 4: plant and controller both configured from
    configs/io/relocated.yaml -- every point at a different address, the
    controller's logic untouched -- and the unchanged scenarios pass."""
    plant, controller = rt_relocated
    for rel in ("faults/feeder_trip_while_running.yaml", "faults/bin_low_blocks_start.yaml"):
        result = run_realtime(scenario(rel), plant, controller, speed=SPEED)
        assert result.passed, (rel, result.detail)


def test_a_map_without_a_status_block_makes_the_run_status_less(tmp_path):
    from services.protocols.map_file import load_map
    from services.simulation.engine.plant_io import build_line_io_image

    text = (REPO / "configs" / "io" / "relocated.yaml").read_text(encoding="utf-8").split("\nstatus:")[0] + "\n"
    path = tmp_path / "no-status.yaml"
    path.write_text(text.replace("ack: 4006", "ack: 4001"), encoding="utf-8")
    register_map, _ = load_map(path, build_line_io_image())
    plant = RealtimePlant(port=0, register_map=register_map)
    ctl = ReferenceController(plant.port, speed=SPEED, register_map=register_map)
    try:
        result = run_realtime(scenario("safety/estop_from_running.yaml"), plant, ctl, speed=SPEED)  # status: from the map
        assert result.passed and result.not_observed == ("line_state",), result.detail
    finally:
        ctl.close()
        plant.close()


@pytest.fixture
def rt_relocated():
    from services.protocols.map_file import load_map
    from services.simulation.engine.plant_io import build_line_io_image

    register_map, _ = load_map(REPO / "configs" / "io" / "relocated.yaml", build_line_io_image())
    plant = RealtimePlant(port=0, register_map=register_map)
    ctl = ReferenceController(plant.port, speed=SPEED, register_map=register_map)
    yield plant, ctl
    ctl.close()
    plant.close()
