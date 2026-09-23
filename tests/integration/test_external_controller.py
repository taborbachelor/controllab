"""External-controller mode (Phase 7 step 3): the plant runs with no
built-in controller, and ControlLab's own LineController -- unmodified --
drives it from the other side of a real Modbus TCP connection.

Most tests interleave one plant tick and one controller scan by hand
(lockstep) over a real localhost socket, so they're deterministic while
still exercising every byte of the protocol path. The last test runs the
controller as a genuinely separate OS process, free-running in real time,
the way it's meant to be deployed.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from services.protocols.external_controller import ExternalController
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.modbus import ModbusClient, ModbusServer
from services.protocols.register_map import IOImageDataStore
from services.visualization.live import WATCHDOG_S, LiveSession, Pacer

REPO = Path(__file__).resolve().parents[2]


class Loop:
    def __init__(self):
        self.plant = LiveSession(external=True)
        store = IOImageDataStore(
            LINE_REGISTER_MAP, lambda: self.plant.io, outputs_writable=True,
            hmi_latches=self.plant.latches, on_output_write=self.plant.note_controller_write,
        )
        self.server = ModbusServer(store, port=0, lock=self.plant.lock)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.client = ModbusClient(port=self.server.server_address[1])
        self.controller = ExternalController(self.client)

    def run(self, ticks, controller=True):
        for _ in range(ticks):
            self.plant.step()
            if controller:
                self.controller.scan_once()

    @property
    def state(self):
        return self.controller.line.state.name.lower()

    def close(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def loop():
    lp = Loop()
    yield lp
    lp.close()


def test_start_over_the_hmi_handshake_runs_the_real_plant(loop):
    loop.plant.command("start")
    loop.run(20)
    assert loop.state == "running"
    plant = loop.plant.rig.plant
    assert plant.conveyor.motor.running and plant.gate.is_open and plant.feeder.motor.running
    assert loop.plant.snapshot()["pending_hmi"] == []  # the controller acknowledged the request


def test_an_hmi_request_is_acted_on_exactly_once(loop):
    loop.plant.command("start")
    loop.run(20)
    loop.plant.command("stop")
    loop.run(60)
    assert loop.state == "idle"
    loop.run(20)  # the stop request must not linger and re-fire
    starts = [e for e in loop.plant.snapshot()["events"] if e["type"] == "command_issued"]
    assert [e["command"] for e in starts] == ["start", "stop"]


def test_a_plant_fault_reaches_the_remote_controller_and_it_shuts_the_line(loop):
    loop.plant.command("start")
    loop.run(20)
    loop.plant.stimulus("feeder_trip", True)
    loop.run(5)
    assert (loop.state, loop.controller.line.fault_reason) == ("faulted", "feeder trip")
    plant = loop.plant.rig.plant
    assert not (plant.conveyor.motor.running or plant.feeder.motor.running or plant.gate.is_open)


def test_full_recovery_driven_entirely_over_modbus(loop):
    loop.plant.command("start")
    loop.run(20)
    loop.plant.stimulus("feeder_trip", True)
    loop.run(5)
    loop.plant.stimulus("feeder_trip", False)
    loop.plant.stimulus("feeder_drive_reset", True)
    loop.plant.command("acknowledge")
    loop.run(3)
    loop.plant.command("reset")
    loop.run(3)
    loop.plant.command("start")
    loop.run(20)
    assert loop.state == "running"
    assert loop.plant.snapshot()["violation"] is None


def test_estop_over_the_wire(loop):
    loop.plant.command("start")
    loop.run(20)
    loop.plant.stimulus("estop", "tripped")
    loop.run(3)
    assert loop.state == "estopped"
    assert not loop.plant.rig.plant.conveyor.motor.running


def test_watchdog_de_energizes_the_plant_when_the_controller_goes_silent(loop):
    loop.plant.command("start")
    loop.run(20)
    assert loop.plant.rig.plant.conveyor.motor.running
    loop.run(round(WATCHDOG_S / 0.1) + 3, controller=False)  # controller stops scanning
    plant = loop.plant.rig.plant
    assert not (plant.conveyor.motor.running or plant.feeder.motor.running)
    assert [e["type"] for e in loop.plant.snapshot()["events"]].count("controller_watchdog") == 1
    assert loop.plant.snapshot()["violation"] is None  # a clean, safe stop -- not a physics violation


def test_watchdog_ignores_a_stopped_line_with_a_speed_setpoint_left_in(loop):
    """Regression: SC-103 stays at 100 % after a fault, but with every run
    command off nothing is energized, so a silent controller is harmless."""
    loop.plant.command("start")
    loop.run(20)
    loop.plant.stimulus("feeder_trip", True)
    loop.run(5)
    assert loop.plant.io.read("SC-103") == 100.0
    loop.run(30, controller=False)
    assert "controller_watchdog" not in [e["type"] for e in loop.plant.snapshot()["events"]]


def test_external_mode_takes_the_same_path_as_the_built_in_controller():
    """The claim this whole step exists to test: the same stimuli, run once
    with the controller built in and once across Modbus, drive the
    controller through the same sequence of states. (Timing can differ by
    a scan -- the wire adds one -- which is why states are compared as a
    sequence, not tick by tick.)"""

    def script(command, stimulus, run, state):
        trace = []

        def record(n):
            for _ in range(n):
                run(1)
                if not trace or trace[-1] != state():
                    trace.append(state())

        command("start"); record(20)
        stimulus("feeder_trip", True); record(5)
        stimulus("feeder_trip", False); stimulus("feeder_drive_reset", True); command("acknowledge"); record(3)
        command("reset"); record(3)
        command("start"); record(20)
        stimulus("estop", "tripped"); record(3)
        # Release first, THEN acknowledge + reset -- the real operator
        # procedure. Doing both in one tick is a genuine race: the one-shot
        # reset is consumed by whichever scan sees it first, and the wire
        # delivers commands a scan later than the built-in path, so the two
        # modes would legitimately resolve it differently (found by this
        # test; see docs/CONTROL-LAB.md Phase 7 step 3).
        stimulus("estop", "healthy"); record(2)
        command("acknowledge"); command("reset"); record(3)
        command("start"); record(20)
        command("stop"); record(40)
        return trace

    builtin = LiveSession()
    built_in_trace = script(builtin.command, builtin.stimulus, lambda n: [builtin.step() for _ in range(n)],
                            lambda: builtin.snapshot()["state"])
    lp = Loop()
    try:
        external_trace = script(lp.plant.command, lp.plant.stimulus, lp.run, lambda: lp.state)
    finally:
        lp.close()

    assert built_in_trace == external_trace
    assert built_in_trace == [
        "starting", "running", "faulted", "idle", "starting", "running",
        "estopped", "idle", "starting", "running", "stopping", "idle",
    ]


def test_separate_processes_free_running_in_real_time():
    """The deployment shape: the plant paced in real time here, the
    controller a separate Python process connected only by TCP."""
    plant = LiveSession(external=True)
    store = IOImageDataStore(
        LINE_REGISTER_MAP, lambda: plant.io, outputs_writable=True,
        hmi_latches=plant.latches, on_output_write=plant.note_controller_write,
    )
    server = ModbusServer(store, port=0, lock=plant.lock)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    pacer = Pacer(plant, speed=5.0)
    pacer.start()
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "scripts" / "external_controller.py"), "--port", str(server.server_address[1]), "--speed", "5"],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        plant.command("start")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not plant.rig.plant.feeder.motor.running:
            time.sleep(0.05)
        assert plant.rig.plant.feeder.motor.running, proc.stderr.read() if proc.poll() is not None else "timed out"
        assert plant.rig.plant.conveyor.motor.running and plant.rig.plant.gate.is_open

        proc.terminate()  # the controller dies mid-run...
        proc.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and plant.rig.plant.conveyor.motor.running:
            time.sleep(0.05)
        assert not plant.rig.plant.conveyor.motor.running  # ...and the watchdog stops the plant
        assert "controller_watchdog" in [e["type"] for e in plant.snapshot()["events"]]
    finally:
        if proc.poll() is None:
            proc.kill()
        pacer.stop()
        pacer.join(timeout=2)
        server.shutdown()
        server.server_close()
