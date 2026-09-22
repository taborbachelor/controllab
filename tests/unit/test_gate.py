from services.simulation.equipment.gate import Gate, GateState

DT = 0.1


def run(gate: Gate, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        gate.step(DT)


def test_opens_in_travel_time():
    g = Gate("XV-1", travel_time_s=2.0)
    g.command(True)
    run(g, 1.9)
    assert g.state == GateState.OPENING
    assert not g.is_open
    run(g, 0.2)
    assert g.is_open


def test_closes_in_travel_time():
    g = Gate("XV-1", travel_time_s=1.0)
    g.command(True)
    run(g, 1.0)
    assert g.is_open
    g.command(False)
    run(g, 1.0)
    assert g.is_closed


def test_reversing_mid_travel_reverses_direction():
    g = Gate("XV-1", travel_time_s=2.0)
    g.command(True)
    run(g, 1.0)
    assert g.state == GateState.OPENING
    g.command(False)
    run(g, 0.1)
    assert g.state == GateState.CLOSING


def test_stuck_gate_never_completes_and_times_out_to_fault():
    g = Gate("XV-1", travel_time_s=1.0, timeout_s=2.0)
    g.stuck = True
    g.command(True)
    run(g, 1.5)
    assert g.state == GateState.OPENING  # would have opened by now if healthy
    run(g, 1.0)
    assert g.state == GateState.FAULT


def test_fault_requires_explicit_clear():
    g = Gate("XV-1", travel_time_s=1.0, timeout_s=1.5)
    g.stuck = True
    g.command(True)
    run(g, 2.0)
    assert g.state == GateState.FAULT
    g.command(False)
    run(g, 1.0)
    assert g.state == GateState.FAULT
    g.clear_fault()
    assert g.is_closed
