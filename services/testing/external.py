"""Running commissioning scenarios against an EXTERNAL controller (docs/
CONTROL-LAB.md §10, Phase 7 step 3b).

build_external_rig() returns an ordinary Rig whose plant has no built-in
controller. Its `line` is a RemoteLine: an object that looks like a
LineController from the outside -- start/stop/reset/acknowledge,
`state`, `fault_reason`, `alarms`, `scan()`, `command_sink` -- but owns
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

from services.control.line_state import LineState
from services.protocols import controller_status
from services.protocols.external_controller import ExternalController
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.modbus import ModbusClient, ModbusServer
from services.protocols.register_map import HmiHandshake, IOImageDataStore, ModbusIOSync
from services.testing.rig import DT, Rig, build_rig

COMMANDS = ("start", "stop", "reset", "acknowledge")


class RemoteLine:
    def __init__(self, rig: Rig) -> None:
        self.handshake = HmiHandshake(LINE_REGISTER_MAP.commands)
        store = IOImageDataStore(LINE_REGISTER_MAP, lambda: rig.io, outputs_writable=True, handshake=self.handshake)
        self._server = ModbusServer(store, port=0)
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        port = self._server.server_address[1]
        self._controller_client = ModbusClient(port=port)
        self._observer = ModbusIOSync(ModbusClient(port=port), LINE_REGISTER_MAP, rig.io)
        self.controller = ExternalController(self._controller_client)
        self.command_sink: Callable[[str], None] | None = None
        self._status = controller_status.decode(self._observer.read_status())

    # ---- the LineController surface the runner and vocabulary use -------

    def _command(self, name: str) -> None:
        if self.command_sink is not None:
            self.command_sink(name)
        self.handshake.request(name)

    def start(self) -> None:
        self._command("start")

    def stop(self) -> None:
        self._command("stop")

    def reset(self) -> None:
        self._command("reset")

    def acknowledge(self) -> None:
        self._command("acknowledge")

    def scan(self, dt: float) -> None:
        self.controller.scan_once(dt)
        self._status = controller_status.decode(self._observer.read_status())

    @property
    def state(self) -> LineState:
        if self._status.state is None:
            raise RuntimeError("the controller published a line_state code the status table doesn't know")
        return self._status.state

    @property
    def fault_reason(self) -> str | None:
        return self._status.fault_reason

    @property
    def alarms(self) -> "_AlarmView":
        # The same all_alarms/latched_alarms/any_unacknowledged_trip surface
        # as AlarmManager, rebuilt from the published status registers.
        return _AlarmView(self._status)

    def close(self) -> None:
        self._controller_client.close()
        self._observer.client.close()
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


__all__ = ["DT", "RemoteLine", "build_external_rig"]
