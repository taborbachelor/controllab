"""The controller status block: codec round-trips, the register access
rules, and drift guards that tie the three code tables to what Control
actually has -- so adding a state, a fault reason, or an alarm to Control
without giving it a code fails here, not silently on a PLC."""
import re
from pathlib import Path

from services.control.line_state import LineState
from services.protocols import controller_status
from services.protocols.controller_status import ALARMS, FAULT_REASONS, LINE_STATES, UNKNOWN, decode, encode
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.modbus import ILLEGAL_DATA_ADDRESS, handle_pdu
from services.protocols.register_map import IOImageDataStore
from services.testing.rig import build_rig, run

LINE_CONTROLLER = Path(__file__).resolve().parents[2] / "services" / "control" / "line_controller.py"


# ---- drift guards ----------------------------------------------------------------

def test_every_line_state_has_a_code():
    assert set(LINE_STATES) == set(LineState)


def test_every_fault_reason_in_line_controller_has_a_code():
    """Collected from the source: the returns of the *_trip_reason()
    methods, _enter_faulted("...") calls, and fault_reason = "..."
    assignments."""
    source = LINE_CONTROLLER.read_text(encoding="utf-8")
    used = set(re.findall(r'return "([^"]+)"', source))
    used |= set(re.findall(r'_enter_faulted\("([^"]+)"\)', source))
    used |= set(re.findall(r'fault_reason = "([^"]+)"', source))
    assert used, "the pattern stopped matching -- update this test, don't delete it"
    assert used <= set(FAULT_REASONS), f"no status code for: {sorted(used - set(FAULT_REASONS))}"


def test_alarm_table_matches_alarm_manager_exactly():
    rig = build_rig()
    assert [(a.id, a.description, a.is_warning) for a in rig.line.alarms.all_alarms] == list(ALARMS)


def test_everything_fits_its_register():
    assert len(ALARMS) <= 16
    assert len(LINE_STATES) < UNKNOWN and len(FAULT_REASONS) < UNKNOWN


# ---- codec -------------------------------------------------------------------------

def test_round_trip_through_a_real_fault():
    rig = build_rig()
    rig.line.start()
    run(rig, 3.0)
    rig.plant.feeder.motor.trip_now = True
    run(rig, 0.3)
    status = decode(encode(rig.line))
    assert status.state == LineState.FAULTED
    assert status.fault_reason == "feeder trip"
    assert [(a.id, a.active, a.acknowledged, a.first_out) for a in status.latched_alarms] == [
        ("M-103.FAULT", True, False, True)
    ]
    assert status.any_unacknowledged_trip()


def test_round_trip_matches_the_alarm_manager_for_every_alarm_field():
    rig = build_rig()
    rig.plant.estop.trip()
    rig.plant.hopper.level_kg = 1_950.0
    run(rig, 0.3)
    rig.line.acknowledge()
    run(rig, 0.1)
    decoded = decode(encode(rig.line)).alarms
    real = rig.line.alarms.all_alarms
    fields = lambda a: (a.id, a.active, a.acknowledged, a.first_out, a.latched)  # noqa: E731
    assert [fields(a) for a in decoded] == [fields(a) for a in real]


def test_an_unknown_reason_is_published_as_unknown_not_guessed():
    rig = build_rig()
    rig.line.fault_reason = "something new"
    assert encode(rig.line)[1] == UNKNOWN
    assert decode(encode(rig.line)).fault_reason == f"unknown reason code {UNKNOWN}"


# ---- register access -----------------------------------------------------------------

def test_built_in_mode_status_is_readable_and_read_only():
    rig = build_rig()
    store = IOImageDataStore(LINE_REGISTER_MAP, lambda: rig.io, status_source=lambda: encode(rig.line))
    rig.plant.estop.trip()
    run(rig, 0.3)
    assert handle_pdu(store, bytes.fromhex("0300010002")) == bytes.fromhex("0304") + bytes((0, 5, 0, 1))  # ESTOPPED, "e-stop"
    assert handle_pdu(store, bytes.fromhex("0600010000")) == bytes((0x86, ILLEGAL_DATA_ADDRESS))


def test_external_mode_status_is_written_by_the_controller():
    rig = build_rig(with_controller=False)
    store = IOImageDataStore(LINE_REGISTER_MAP, lambda: rig.io, outputs_writable=True)
    handle_pdu(store, bytes.fromhex("100001000204" + "0002" + "0000"))  # RUNNING, no fault
    assert store.status_values[:2] == [2, 0]
    assert handle_pdu(store, bytes.fromhex("0300010001")) == bytes.fromhex("03020002")


def test_status_codes_are_in_the_generated_document():
    doc = (Path(__file__).resolve().parents[2] / "docs" / "MODBUS-MAP.md").read_text(encoding="utf-8")
    assert controller_status.render_markdown() in doc
