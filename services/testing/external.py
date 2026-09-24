"""Running commissioning scenarios against an EXTERNAL controller (docs/
CONTROL-LAB.md §10, Phase 7 step 3b).

build_external_rig() returns an ordinary Rig whose plant has no built-in
controller. Its `line` is a RemoteLine: an object that looks like a
LineController from the outside -- start/stop/reset/acknowledge,
`state`, `fault_reason`, `start_inhibit`, `alarms`, `scan()`, `command_sink` -- but owns
none of the logic. Behind it:

- the plant's I/O image served over Modbus TCP on localhost, outputs
  and status writable, HMI commands through the request/ack handshake
  (services/protocols/register_map.py);
- the reference external controller (services/protocols/
  external_controller.py) on its own Modbus connection;
- a second, separate "observer" connection that reads the controller's
  published status block after each scan.

So the scenario runner, the vocabulary, the invariants, the EventLog and
every scenario file work unchanged -- and everything they learn about the
controller arrived over Modbus. Commands go out as HMI requests;
state comes back as status registers; the controller itself only ever
sees field I/O.

`scan()` runs one controller scan and then refreshes the status, and
tick() calls it before advancing the plant -- the same order as the
built-in controller (Control scans, then the plant moves), so timing is
comparable scenario for scenario. It's lockstep (one controller scan per
plant tick), not free-running, which is what makes the suite
deterministic; the free-running two-process deployment has its own test
(tests/integration/test_external_controller.py).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import nullcontext

from services.control.line_state import LineMode, LineState
from services.protocols import controller_status
from services.protocols.external_controller import ExternalController
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.modbus import ModbusClient, ModbusServer
from services.protocols.register_map import HmiHandshake, IOImageDataStore, ModbusIOSync
from services.testing.rig import DT, Rig, build_rig
from services.testing.vocabulary import NotObservable

COMMANDS = ("start", "stop", "reset", "acknowledge", "select_auto", "select_manual", "start_conveyor", "stop_conveyor", "open_gate", "close_gate", "start_feeder", "stop_feeder")


class ObservedLine:
    """A controller on the far side of Modbus, seen the way an HMI sees
    it: commands go out as HMI requests through `handshake`, state comes
    back from the status registers read by `observer`. The LineController
    surface the runner and vocabulary use, with none of the logic.

    `refresh()` reads the status over the wire, so it must never be
    called while holding `lock` (the Modbus server needs that lock to
    answer). `lock` guards the handshake when the server runs
    concurrently (the real-time runner); lockstep needs none.

    `status=False` (Phase 9 step 3): the controller doesn't publish the
    status block. Commands still go out; every state property raises
    NotObservable instead of reporting registers nobody wrote (which
    would read 0 = IDLE, a plausible-looking lie)."""

    def __init__(self, handshake: HmiHandshake, observer: ModbusIOSync, lock=None, status: bool = True) -> None:
        self.handshake = handshake
        self._observer = observer
        self._lock = lock if lock is not None else nullcontext()
        self.publishes_status = status
        self.command_sink: Callable[[str], None] | None = None
        self._status = None
        self.refresh()

    def refresh(self) -> None:
        if self.publishes_status:
            self._status = controller_status.decode(self._observer.read_status())

    def _published(self) -> controller_status.ControllerStatus:
        if self._status is None:
            raise NotObservable("the controller under test doesn't publish ControlLab's status block")
        return self._status

    def scan(self, dt: float) -> None:
        self.refresh()

    # ---- the LineController surface the runner and vocabulary use -------

    def _command(self, name: str) -> None:
        if self.command_sink is not None:
            self.command_sink(name)
        with self._lock:
            self.handshake.request(name)

    def start(self) -> None:
        self._command("start")

    def stop(self) -> None:
        self._command("stop")

    def reset(self) -> None:
        self._command("reset")

    def acknowledge(self) -> None:
        self._command("acknowledge")

    def select_auto(self) -> None:
        self._command("select_auto")

    def select_manual(self) -> None:
        self._command("select_manual")

    def start_conveyor(self) -> None:
        self._command("start_conveyor")

    def stop_conveyor(self) -> None:
        self._command("stop_conveyor")

    def open_gate(self) -> None:
        self._command("open_gate")

    def close_gate(self) -> None:
        self._command("close_gate")

    def start_feeder(self) -> None:
        self._command("start_feeder")

    def stop_feeder(self) -> None:
        self._command("stop_feeder")

    @property
    def state(self) -> LineState:
        status = self._published()
        if status.state is None:
            raise RuntimeError("the controller published a line_state code the status table doesn't know")
        return status.state

    @property
    def mode(self) -> LineMode:
        status = self._published()
        if status.mode is None:
            raise RuntimeError("the controller published a mode code the status table doesn't know")
        return status.mode

    @property
    def fault_reason(self) -> str | None:
        return self._published().fault_reason

    @property
    def start_inhibit(self):
        return self._published().start_inhibit

    @property
    def alarms(self) -> "_AlarmView":
        # The same all_alarms/latched_alarms/any_unacknowledged_trip surface
        # as AlarmManager, rebuilt from the published status registers.
        return _AlarmView(self._published())

    def close(self) -> None:
        self._observer.client.close()


class RemoteLine(ObservedLine):
    """ObservedLine plus, in-process, the Modbus server for the plant and
    the reference external controller, scanned in lockstep: `scan()` runs
    one controller scan, then refreshes the status."""

    def __init__(self, rig: Rig) -> None:
        handshake = HmiHandshake(LINE_REGISTER_MAP.commands)
        store = IOImageDataStore(LINE_REGISTER_MAP, lambda: rig.io, outputs_writable=True, handshake=handshake)
        self._server = ModbusServer(store, port=0)
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        port = self._server.server_address[1]
        self._controller_client = ModbusClient(port=port)
        self.controller = ExternalController(self._controller_client)
        super().__init__(handshake, ModbusIOSync(ModbusClient(port=port), LINE_REGISTER_MAP, rig.io))

    def scan(self, dt: float) -> None:
        self.controller.scan_once(dt)
        self.refresh()

    def close(self) -> None:
        self._controller_client.close()
        super().close()
        self._server.shutdown()
        self._server.server_close()


class _AlarmView:
    def __init__(self, status: controller_status.ControllerStatus) -> None:
        self._status = status

    @property
    def all_alarms(self):
        return self._status.alarms

    @property
    def latched_alarms(self):
        return self._status.latched_alarms

    def any_unacknowledged_trip(self) -> bool:
        return self._status.any_unacknowledged_trip()


def build_external_rig() -> Rig:
    """A Rig whose controller is on the far side of Modbus. Call
    `rig.line.close()` when done (run_scenario does)."""
    rig = build_rig(with_controller=False)
    rig.line = RemoteLine(rig)
    return rig


__all__ = ["DT", "ObservedLine", "RemoteLine", "build_external_rig"]
