"""The feeder jam in the plant model (Phase 4 completion): flow stops, the
drive keeps running, and the plug switch makes after plug_detect_s of
pushing against the jam -- then stays made until the jam is cleared."""
import pytest

from services.simulation.equipment.feeder import Feeder
from services.simulation.equipment.motor import MotorState

DT = 0.1


def running_feeder(plug_detect_s=0.5):
    f = Feeder("FDR", max_rate_kg_s=5.0, start_delay_s=0.0, plug_detect_s=plug_detect_s)
    f.command(True, 100.0)
    f.step(DT)
    assert f.motor.state == MotorState.RUNNING and f.current_rate_kg_s() == 5.0
    return f


def test_a_jam_stops_the_flow_but_not_the_drive():
    f = running_feeder()
    f.jammed = True
    f.step(DT)
    assert f.current_rate_kg_s() == 0.0
    assert f.motor.running and not f.motor.fault  # nothing the drive reports is wrong


def test_the_plug_switch_makes_only_after_pushing_against_the_jam():
    f = running_feeder(plug_detect_s=0.5)
    f.jammed = True
    for _ in range(4):
        f.step(DT)
    assert not f.plugged  # 0.4 s
    f.step(DT)
    assert f.plugged      # 0.5 s


def test_a_jam_on_a_stopped_feeder_is_not_detected_until_it_runs():
    f = Feeder("FDR", max_rate_kg_s=5.0, start_delay_s=0.0, plug_detect_s=0.5)
    f.jammed = True
    for _ in range(20):
        f.step(DT)
    assert not f.plugged  # nothing pushed into the blocked chute


def test_the_plug_switch_stays_made_while_stopped_and_clears_with_the_jam():
    f = running_feeder()
    f.jammed = True
    for _ in range(5):
        f.step(DT)
    f.command(False)
    for _ in range(10):
        f.step(DT)
    assert not f.motor.running and f.plugged  # the chute stays packed
    f.jammed = False
    f.step(DT)
    assert not f.plugged


@pytest.mark.parametrize("seconds", [0.0, 0.3])
def test_plug_detect_time_is_configurable(seconds):
    f = running_feeder(plug_detect_s=seconds)
    f.jammed = True
    for _ in range(round(seconds / DT) or 1):
        f.step(DT)
    assert f.plugged
