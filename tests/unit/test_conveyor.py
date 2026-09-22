from services.simulation.equipment.conveyor import Conveyor

DT = 0.1


def run(conveyor: Conveyor, seconds: float):
    delivered = 0.0
    for _ in range(round(seconds / DT)):
        delivered += conveyor.step(DT)
    return delivered


def test_material_spills_when_fed_onto_stopped_belt():
    c = Conveyor("CV-1", length_m=10.0, speed_m_s=2.0)
    spilled = c.load(50.0)
    assert spilled == 50.0
    assert c.mass_on_belt_kg == 0.0


def test_material_transits_in_expected_time():
    c = Conveyor("CV-1", length_m=10.0, speed_m_s=2.0, start_delay_s=0.0)
    c.command(True)
    run(c, 0.1)  # motor confirms running
    spilled = c.load(20.0)
    assert spilled == 0.0
    assert c.mass_on_belt_kg == 20.0

    # transit time is 5.0s; nothing should arrive before then
    delivered = run(c, 4.8)
    assert delivered == 0.0
    assert c.mass_on_belt_kg == 20.0

    delivered = run(c, 0.3)
    assert delivered == 20.0
    assert c.mass_on_belt_kg == 0.0


def test_belt_slip_fault_spills_even_while_motor_runs():
    c = Conveyor("CV-1", length_m=10.0, speed_m_s=2.0, start_delay_s=0.0)
    c.command(True)
    run(c, 0.1)
    assert c.motor.running
    c.motion_switch_stuck_false = True
    assert not c.motion_confirmed
    spilled = c.load(15.0)
    assert spilled == 15.0
