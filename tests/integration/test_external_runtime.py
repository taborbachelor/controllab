"""Your own controller (docs/CONNECTING-A-CONTROLLER.md): a free-running
controller ControlLab doesn't manage, already polling the plant's port.

The stand-in for "your controller" is ControlLab's reference controller,
started here the way an engineer starts their PLC: independently of the
runner, which can only restart it through a command it's given, or not
at all.
"""
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from services.cli import main
from services.protocols import external_controller
from services.protocols.modbus import exposure_warning
from services.testing.realtime import ControllerRestartError, ExternalController, RealtimePlant, run_realtime
from services.testing.scenario import Scenario

REPO = Path(__file__).resolve().parents[2]
SPEED = 4.0


def scenario(rel):
    return Scenario.load(REPO / "scenarios" / rel)


def run_rt(*args, **kwargs):
    """Rerun (at most twice) only a run the runner invalidated because this
    host fell behind real time, as tests/integration/test_realtime.py does."""
    for _ in range(3):
        result = run_realtime(*args, **kwargs)
        if result.passed or "behind real time" not in result.detail:
            return result
    return result


class YourController:
    """A controller running on its own: it keeps trying to reach the plant
    until it can, then scans until stopped."""

    def __init__(self, port, speed):
        self.stop = threading.Event()

        def loop():
            while not self.stop.is_set():
                try:
                    external_controller.run("127.0.0.1", port, speed, self.stop)
                except OSError:
                    self.stop.wait(0.05)

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)


@pytest.fixture
def plant():
    p = RealtimePlant(port=0)
    yield p
    p.close()


def test_without_a_restart_each_scenario_still_starts_from_a_clean_idle(plant):
    """The controller is never restarted: a scenario that leaves it FAULTED
    with a latched alarm is followed by one that needs a clean IDLE, and
    the power-up procedure (acknowledge, reset) is what gets it there."""
    yours = YourController(plant.port, SPEED)
    try:
        controller = ExternalController()
        tripped = run_rt(scenario("faults/feeder_trip_while_running.yaml"), plant, controller, speed=SPEED)
        assert tripped.passed, tripped.detail
        refused = run_rt(scenario("faults/bin_low_blocks_start.yaml"), plant, controller, speed=SPEED)
        assert refused.passed, refused.detail
    finally:
        yours.close()
    assert "NOT restarted" in controller.name  # every report says so


def test_the_restart_command_runs_before_every_scenario(plant, tmp_path):
    log = tmp_path / "restarts.txt"
    script = tmp_path / "restart.py"
    script.write_text(f"open({str(log)!r}, 'a').write('restarted\\n')\n")
    controller = ExternalController(f'"{sys.executable}" "{script}"')
    assert "restarted before each scenario" in controller.name
    yours = YourController(plant.port, SPEED)
    try:
        for rel in ("startup/normal_start.yaml", "safety/estop_from_running.yaml"):
            result = run_rt(scenario(rel), plant, controller, speed=SPEED)
            assert result.passed, result.detail
    finally:
        yours.close()
    assert log.read_text().splitlines().count("restarted") >= 2


def test_a_failing_restart_command_stops_the_run_and_says_why(tmp_path):
    script = tmp_path / "fail.py"
    script.write_text("import sys\nprint('PLC not found')\nsys.exit(3)\n")
    controller = ExternalController(f'"{sys.executable}" "{script}"')
    with pytest.raises(ControllerRestartError) as e:
        controller.restart()
    assert "exited 3" in str(e.value) and "PLC not found" in str(e.value)


def test_the_cli_runs_your_scenario_against_your_controller(tmp_path, capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    f = tmp_path / "estop.yaml"
    f.write_text((REPO / "scenarios" / "safety" / "estop_from_running.yaml").read_text(encoding="utf-8"),
                 encoding="utf-8")
    yours = YourController(port, 1.0)  # a real controller's timers run on wall time: the plant runs at 1x
    try:
        code = main(["test", "--runtime", "external", "--modbus-port", str(port), str(f)])
    finally:
        yours.close()
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Your controller over Modbus TCP (real time): external controller, NOT restarted" in out
    assert "1/1 scenarios passed" in out


def test_real_time_options_are_refused_for_a_lockstep_runtime():
    for flags in (["--bind", "0.0.0.0"], ["--restart-cmd", "x"], ["--no-status"], ["--modbus-port", "5021"]):
        with pytest.raises(SystemExit) as e:
            main(["test", "normal_start", *flags])
        assert "real-time runtime" in str(e.value)
    with pytest.raises(SystemExit) as e:
        main(["test", "normal_start", "--runtime", "openplc", "--restart-cmd", "x"])
    assert "--runtime external" in str(e.value)


def test_serving_beyond_this_machine_is_warned_about():
    assert exposure_warning("127.0.0.1") is None
    assert exposure_warning("localhost") is None
    assert exposure_warning("::1") is None
    for host in ("0.0.0.0", "192.168.1.20", "plant-bench"):
        warning = exposure_warning(host)
        assert warning and "no authentication" in warning and host in warning


def test_every_option_the_guide_mentions_exists():
    import re
    import subprocess

    guide = (REPO / "docs" / "CONNECTING-A-CONTROLLER.md").read_text(encoding="utf-8")
    helps = "".join(
        subprocess.run([sys.executable, *cmd, "--help"], capture_output=True, text=True, cwd=REPO).stdout
        for cmd in (["-m", "services.cli", "test"], ["scripts/scenario_report.py"], ["scripts/dashboard.py"])
    )
    mentioned = set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", guide))
    assert mentioned >= {"--runtime", "--bind", "--restart-cmd", "--map", "--no-status", "--external"}
    assert {flag for flag in mentioned if flag not in helps} == set()
