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


def test_a_stopped_or_slipping_belt_holds_its_load_and_resumes_where_it_left_off():
    """The belt's clock is its own travel, not plant time. (It was plant time,
    so a stopped belt kept delivering and no scenario could tell whether a
    stop sequence purged the belt at all.)"""
    c = Conveyor("CV-1", length_m=10.0, speed_m_s=2.0, start_delay_s=0.0)  # 5.0 s transit
    c.command(True)
    run(c, 0.1)
    c.load(20.0)
    assert run(c, 2.0) == 0.0  # 2.0 s of travel so far
    c.command(False)
    assert run(c, 10.0) == 0.0 and c.mass_on_belt_kg == 20.0  # stopped: held in place
    c.command(True)
    c.motion_switch_stuck_false = True
    assert run(c, 10.0) == 0.0 and c.mass_on_belt_kg == 20.0  # slipping: still held
    c.motion_switch_stuck_false = False
    assert run(c, 2.9) == 0.0  # 4.9 s of travel
    assert run(c, 0.2) == 20.0  # arrives after 5.0 s of travel, however long it sat
