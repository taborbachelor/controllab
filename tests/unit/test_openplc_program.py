"""The OpenPLC example program (examples/openplc/controllab_line.st) can't
run in this suite -- OpenPLC isn't a test dependency -- but its I/O
addresses are hand-written against the register map, so they can drift.
This parses every located variable in the program and checks it against
LINE_REGISTER_MAP.controller_ranges() and OpenPLC's documented mapping of
a slave device's polled data (modbus_master.cpp: bool_input[100+(i/8)][i%8],
int_input[100+i] with the holding-read range after the input registers,
bool_output/int_output likewise from 100)."""
import re
from pathlib import Path

from services.protocols.controller_status import REGISTER_NAMES
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.register_map import COIL, DISCRETE_INPUT, HOLDING_REGISTER, INPUT_REGISTER

ST = (Path(__file__).resolve().parents[2] / "examples" / "openplc" / "controllab_line.st").read_text(encoding="utf-8")
LOCATED = {
    name: location
    for name, location in re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+AT\s+(%[IQ][XW][0-9.]+)\s*:", ST, re.M)
}


def st_name(tag: str) -> str:
    """ST identifiers can't contain '-' or '.': M-103.RUNNING -> M103_RUNNING, LT-101 -> LT_101."""
    base, _, suffix = tag.partition(".")
    prefix, _, number = base.partition("-")
    joined = f"{prefix}{number}" if suffix else f"{prefix}_{number}"
    return f"{joined}_{suffix}" if suffix else joined


def bit_address(prefix: str, i: int) -> str:
    return f"{prefix}{100 + i // 8}.{i % 8}"


def test_every_located_variable_is_where_openplc_will_put_it():
    ranges = LINE_REGISTER_MAP.controller_ranges()
    expected = {}
    di = LINE_REGISTER_MAP.by_table(DISCRETE_INPUT)
    for i, a in enumerate(range(ranges.discrete_inputs[0], sum(ranges.discrete_inputs))):
        expected[st_name(di[a].tag)] = bit_address("%IX", i)
    coils = LINE_REGISTER_MAP.by_table(COIL)
    for i, a in enumerate(range(ranges.coils[0], sum(ranges.coils))):
        expected[st_name(coils[a].tag)] = bit_address("%QX", i)
    ir = LINE_REGISTER_MAP.by_table(INPUT_REGISTER)
    for i, a in enumerate(range(ranges.input_registers[0], sum(ranges.input_registers))):
        expected[st_name(ir[a].tag)] = f"%IW{100 + i}"
    expected["HMI_REQUEST"] = f"%IW{100 + ranges.input_registers[1]}"  # holding-read follows the input registers

    hr = LINE_REGISTER_MAP.by_table(HOLDING_REGISTER)
    status = {r.address: f"ST_{r.name.upper()}" for r in LINE_REGISTER_MAP.status_registers}
    for i, a in enumerate(range(ranges.holding_write[0], sum(ranges.holding_write))):
        name = st_name(hr[a].tag) if a in hr else status.get(a, "HMI_ACK" if a == LINE_REGISTER_MAP.hmi_ack else None)
        expected[name] = f"%QW{100 + i}"

    assert LOCATED == expected


def test_status_registers_publish_in_controller_status_order():
    assert [f"ST_{n.upper()}" for n in REGISTER_NAMES] == [
        name for name, loc in sorted(LOCATED.items(), key=lambda kv: kv[1]) if name.startswith("ST_")
    ]


def test_no_identifiers_collide_case_insensitively():
    """IEC 61131-3 identifiers are case-insensitive -- a Python-style
    CONSTANT vs variable pair (PURGE_SCANS / purge_scans) broke the first
    compile against OpenPLC's MatIEC."""
    names = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:AT\s+%\S+\s*)?:\s*(?:ARRAY|BOOL|INT|WORD)", ST, re.M)
    lowered = [n.lower() for n in names]
    assert len(lowered) == len(set(lowered)), sorted(n for n in names if lowered.count(n.lower()) > 1)


def test_alarm_table_matches_the_published_alarm_bits():
    """The alarm arrays, every alarm loop, the alarm_cond assignments and the
    warning exclusions all follow controller_status.ALARMS. Appending an alarm
    to the Python and not the program would otherwise go unnoticed until a
    PLC run: the loops would never publish the new bit."""
    from services.protocols.controller_status import ALARMS

    last = len(ALARMS) - 1
    assert set(re.findall(r"alarm_\w+ : ARRAY\[0\.\.(\d+)\] OF BOOL", ST)) == {str(last)}
    loops = re.findall(r"FOR i := 0 TO (\d+) DO", ST)
    hmi_last = str(len(LINE_REGISTER_MAP.commands) - 1)  # the HMI request loop
    assert loops.count(str(last)) == 4 and set(loops) <= {hmi_last, str(last)}
    assigned = sorted(int(i) for i in re.findall(r"^\s*alarm_cond\[(\d+)\] :=", ST, re.M))
    assert assigned == list(range(len(ALARMS)))
    for i, (alarm_id, _, _) in enumerate(ALARMS):
        assert re.search(rf"alarm_cond\[{i}\] :=.*\(\* {re.escape(alarm_id)}", ST), alarm_id
    warnings = {i for i, (_, _, is_warning) in enumerate(ALARMS) if is_warning}
    line = next(l for l in ST.splitlines() if "unacked_trip := TRUE" in l)
    assert {int(i) for i in re.findall(r"i <> (\d+)", line)} == warnings


def test_the_belt_clearing_trips_match_the_python_controller():
    """The ST program lists the upstream trips by reason code; Python by name
    (LineController.CLEAR_BELT_ON). Tied here so the two can't drift."""
    from services.control.line_controller import CLEAR_BELT_ON
    from services.protocols.controller_status import FAULT_REASONS

    lists = re.findall(r"clearing := M104_RUN AND \(([^)]*)\)", ST)
    assert len(lists) == 4 and len(set(lists)) == 1  # the STARTING, RUNNING, STOPPING and MANUAL trip entries
    assert {FAULT_REASONS[int(c)] for c in re.findall(r"trip = (\d+)", lists[0])} == set(CLEAR_BELT_ON)


def test_every_hmi_command_bit_is_decoded_in_bit_order():
    """The request word's CASE takes one bit per command, 0..n-1, n being the
    register map's command count: a command appended to the map and not to
    the program would be requested and never acknowledged."""
    assert re.search(rf"FOR i := 0 TO {len(LINE_REGISTER_MAP.commands) - 1} DO\s+bit := SHL", ST)
    cases = [int(n) for n in re.findall(r"^\s*(\d+): \w+_req := TRUE;", ST, re.M)]
    assert cases == list(range(len(LINE_REGISTER_MAP.commands)))


def test_the_transmitter_high_high_debounce_matches_the_python_controller():
    """The PLC counts the 0.5 s debounce in 100 ms task scans."""
    import inspect

    from services.control.interlocks import Interlocks
    from services.testing.rig import DT

    default = inspect.signature(Interlocks).parameters["hh_weight_debounce_s"].default
    assert re.search(rf"LIM_HH_DEBOUNCE : INT := {round(default / DT)};", ST)
    assert "hopper_high_high := hopper_hh_switch OR hopper_hh_weight_vote;" in ST
