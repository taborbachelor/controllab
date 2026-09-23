"""Controllers that don't publish a status block (Phase 9 step 3): an
expectation on the controller's state is reported not observed, never
failed and never silently passed.

The runner tests here are deterministic: ControlLab's own controller in
lockstep behind a wrapper that withholds its state exactly as a
status-less external controller would. The real-time path against a
free-running controller is tests/integration/test_realtime.py.
"""
from pathlib import Path

import pytest

from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.register_map import HmiHandshake
from services.telemetry.events import EventLog
from services.telemetry.tag_history import TagHistory
from services.testing.external import ObservedLine
from services.testing.invariants import Invariants
from services.testing.rig import build_rig
from services.testing.runner import _Telemetry, _tick, execute
from services.testing.scenario import Scenario
from services.testing.vocabulary import CONTROLLER_FIELDS, READ_FIELDS, NotObservable, read_field

REPO = Path(__file__).resolve().parents[2]


class _NoObserver:
    def read_status(self):
        raise AssertionError("a status-less ObservedLine must never read the status registers")


def test_exactly_the_controller_fields_are_unobservable_without_a_status_block():
    """Ties CONTROLLER_FIELDS to READ_FIELDS: a new field that reads the
    controller can't slip through as always observable."""
    rig = build_rig(with_controller=False)
    rig.line = ObservedLine(HmiHandshake(LINE_REGISTER_MAP.commands), _NoObserver(), status=False)
    unobservable = set()
    for key in READ_FIELDS:
        try:
            read_field(rig, key)
        except NotObservable:
            unobservable.add(key)
    assert unobservable == CONTROLLER_FIELDS


class Blind:
    """A LineController with its state withheld: commands and scans go
    through, every state read raises NotObservable."""

    def __init__(self, line):
        self._line = line

    def __getattr__(self, name):  # start/stop/reset/acknowledge/scan
        return getattr(self._line, name)

    @property
    def command_sink(self):
        return self._line.command_sink

    @command_sink.setter
    def command_sink(self, sink):
        self._line.command_sink = sink

    def _withheld(self):
        raise NotObservable("withheld")

    state = property(_withheld)
    fault_reason = property(_withheld)
    alarms = property(_withheld)
    start_inhibit = property(_withheld)


def run_blind(rel):
    rig = build_rig()
    rig.line = Blind(rig.line)
    telemetry = _Telemetry(EventLog(rig.line, controller_state=False), TagHistory(rig.io))
    return execute(rig, Scenario.load(REPO / "scenarios" / rel), lambda: _tick(rig, telemetry), Invariants(rig), telemetry)


def test_observable_expectations_still_decide_and_the_rest_are_named():
    result = run_blind("safety/estop_from_running.yaml")  # line_state + both motors stopped
    assert result.passed and not result.not_observable
    assert result.not_observed == ("line_state",)
    assert "not observed: line_state" in result.detail


def test_given_running_is_reached_from_field_evidence():
    result = run_blind("startup/normal_start.yaml")  # needs no given, but proves the run itself
    assert result.passed and result.not_observed == ("line_state",)
    tripped = run_blind("faults/belt_slip_stops_feeder.yaml")  # given: running
    assert tripped.passed and tripped.not_observed == ("line_state", "fault_reason")


def test_a_scenario_with_nothing_observable_is_neither_passed_nor_failed():
    result = run_blind("faults/bin_low_blocks_start.yaml")  # line_state + start_inhibit only
    assert not result.passed and result.not_observable
    assert result.not_observed == ("line_state", "start_inhibit")
    assert result.detail.startswith("not observable:")


def test_without_controller_state_the_event_log_records_commands_only():
    result = run_blind("safety/estop_from_running.yaml")
    assert {e.type for e in result.events} == {"command_issued"}


@pytest.mark.parametrize("prop", ["state", "fault_reason", "alarms", "start_inhibit"])
def test_a_statusless_observed_line_never_reports_zeros_as_idle(prop):
    line = ObservedLine(HmiHandshake(LINE_REGISTER_MAP.commands), _NoObserver(), status=False)
    with pytest.raises(NotObservable):
        getattr(line, prop)
