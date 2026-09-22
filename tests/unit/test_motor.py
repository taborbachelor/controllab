from services.simulation.equipment.motor import Motor, MotorState

DT = 0.1


def run(motor: Motor, seconds: float) -> None:
    ticks = round(seconds / DT)
    for _ in range(ticks):
        motor.step(DT)


def test_starts_after_start_delay():
    m = Motor("M-1", start_delay_s=0.5)
    m.command(True)
    run(m, 0.4)
    assert m.state == MotorState.STARTING
    assert not m.running
    run(m, 0.1)
    assert m.state == MotorState.RUNNING
    assert m.running


def test_stops_after_stop_delay():
    m = Motor("M-1", start_delay_s=0.0, stop_delay_s=0.3)
    m.command(True)
    run(m, 0.1)
    assert m.running
    m.command(False)
    run(m, 0.2)
    assert m.state == MotorState.STOPPING
    run(m, 0.1)
    assert m.state == MotorState.STOPPED


def test_run_command_dropped_during_starting_aborts_start():
    m = Motor("M-1", start_delay_s=0.5)
    m.command(True)
    run(m, 0.2)
    assert m.state == MotorState.STARTING
    m.command(False)
    run(m, 0.1)
    assert m.state == MotorState.STOPPED
    assert not m.running


def test_fail_to_start_never_confirms_running():
    m = Motor("M-1", start_delay_s=0.2)
    m.fail_to_start = True
    m.command(True)
    run(m, 5.0)
    assert m.state == MotorState.STARTING
    assert not m.running


def test_trip_while_running_goes_to_fault():
    m = Motor("M-1", start_delay_s=0.0)
    m.command(True)
    run(m, 0.1)
    assert m.running
    m.trip_now = True
    run(m, 0.1)
    assert m.state == MotorState.FAULT
    assert m.fault
    assert not m.run_command


def test_fault_requires_explicit_clear():
    m = Motor("M-1", start_delay_s=0.0)
    m.command(True)
    run(m, 0.1)
    m.trip_now = True
    run(m, 0.1)
    assert m.state == MotorState.FAULT
    m.trip_now = False
    m.command(True)
    run(m, 1.0)
    assert m.state == MotorState.FAULT  # command alone doesn't clear it
    m.clear_fault()
    assert m.state == MotorState.STOPPED


def test_estop_overrides_and_requires_explicit_reset():
    m = Motor("M-1", start_delay_s=0.0)
    m.command(True)
    run(m, 0.1)
    assert m.running
    m.estop()
    assert m.state == MotorState.ESTOP
    assert not m.run_command
    run(m, 5.0)
    assert m.state == MotorState.ESTOP  # step() is a no-op in ESTOP
    m.estop_reset()
    assert m.state == MotorState.STOPPED
    assert not m.running  # no auto-restart after reset
