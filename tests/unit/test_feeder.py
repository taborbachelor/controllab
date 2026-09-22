from services.simulation.equipment.feeder import Feeder

DT = 0.1


def run(feeder: Feeder, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        feeder.step(DT)


def test_no_flow_while_motor_not_running():
    f = Feeder("FDR-1", max_rate_kg_s=5.0, start_delay_s=1.0)
    f.command(True, speed_pct=100.0)
    run(f, 0.5)  # still starting
    assert f.current_rate_kg_s() == 0.0


def test_rate_scales_with_speed_once_running():
    f = Feeder("FDR-1", max_rate_kg_s=5.0, start_delay_s=0.0)
    f.command(True, speed_pct=40.0)
    run(f, 0.1)
    assert f.motor.running
    assert f.current_rate_kg_s() == 2.0


def test_speed_command_clamped_to_0_100():
    f = Feeder("FDR-1", max_rate_kg_s=5.0)
    f.command(True, speed_pct=150.0)
    assert f.speed_pct == 100.0
    f.command(True, speed_pct=-10.0)
    assert f.speed_pct == 0.0
