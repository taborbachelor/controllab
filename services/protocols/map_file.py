"""User-supplied I/O mapping files (docs/CONTROL-LAB.md §10, Phase 9
step 4): the plant's tags at the addresses an EXISTING PLC program's I/O
configuration expects, instead of the program being rewritten to fit
ControlLab's own map. That is the usual direction in virtual
commissioning: the simulation adapts to the controller.

A map file is YAML, loaded into the same RegisterMap every other map is
(services/protocols/register_map.py), and then validated by the same
RegisterMap.validate() -- every tag mapped exactly once, in the table its
type belongs in, analog full scale inside 16 bits, no collisions, and the
controller's view five contiguous ranges a standard PLC master can poll:

    name: Relocated remote-I/O layout          # shown in the generated document
    discrete_inputs:                           # address: tag
      1000: LSL-101
    input_registers:                           # address: {tag, scale, full_scale}
      2000: {tag: LT-101, scale: 100, full_scale: 100}
    coils:
      3000: XV-102.CMD_OPEN
    holding_registers:
      4000: {tag: SC-103, scale: 100, full_scale: 100}
    hmi:                                       # operator commands to the controller
      request: 4100                            # holding register it reads
      ack: 4001                                # holding register it writes
      commands:                                # SCADA pushbutton coil per command;
        start: 3100                            # their address order is the bit
        stop: 3101                             # order in the request/ack words
        reset: 3102
        acknowledge: 3103
    status:                                    # OPTIONAL: ControlLab's status block
      line_state: 4002                         # (all six or none)
      ...

**`status` is all or nothing, and leaving it out is a statement:** the
controller publishes no status block, so a real-time run against this map
reports expectations on the controller's state as not observable (Phase 9
step 3) instead of decoding registers nobody writes. A partial block is
refused: services/protocols/controller_status.py decodes the six
registers together.

Strict on purpose: an unknown key, a non-integer address, or a missing
section is an error naming the file, never silently ignored -- a
commissioning contract with a typo in it should fail at load time, not
show up as a wrong reading on a PLC.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from services.protocols.controller_status import REGISTER_NAMES as STATUS_NAMES
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.register_map import (
    COIL,
    DISCRETE_INPUT,
    HOLDING_REGISTER,
    INPUT_REGISTER,
    HmiCoil,
    HmiSetpoint,
    Point,
    RegisterMap,
    StatusRegister,
)
from services.simulation.engine.io_image import IOImage

TABLES = {
    "discrete_inputs": DISCRETE_INPUT,
    "input_registers": INPUT_REGISTER,
    "coils": COIL,
    "holding_registers": HOLDING_REGISTER,
}
ANALOG = {INPUT_REGISTER, HOLDING_REGISTER}
# What each command and status register means doesn't change with its
# address, so the generated document borrows the line map's wording.
_COMMAND_TEXT = {h.command: h.description for h in LINE_REGISTER_MAP.hmi_coils}
_STATUS_TEXT = {r.name: r.description for r in LINE_REGISTER_MAP.status_registers}
TOP_LEVEL = {"name", *TABLES, "hmi", "status"}


class MapFileError(ValueError):
    pass


def load_map(path: Path, io: IOImage) -> tuple[RegisterMap, str]:
    """(the validated map, its name). Raises MapFileError listing every
    problem found, including RegisterMap.validate()'s against `io`."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise MapFileError(f"{path}: invalid YAML: {e}") from e
    problems: list[str] = []
    register_map, name = _parse(raw, problems)
    if not problems:
        try:
            register_map.validate(io)
        except ValueError as e:
            problems += [line.strip() for line in str(e).splitlines()[1:]]
    if problems:
        raise MapFileError(f"{path}: invalid I/O map:\n  " + "\n  ".join(problems))
    return register_map, name


def _parse(raw: object, problems: list[str]) -> tuple[RegisterMap, str]:
    if not isinstance(raw, dict):
        problems.append("top level must be a mapping")
        return RegisterMap(points=()), ""
    problems += [f"unknown key {k!r} (known: {sorted(TOP_LEVEL)})" for k in raw if k not in TOP_LEVEL]
    name = raw.get("name", "")
    if not isinstance(name, str):
        problems.append("name must be text")
        name = ""

    points: list[Point] = []
    for key, table in TABLES.items():
        section = raw.get(key)
        if section is None:
            problems.append(f"{key}: missing (every table the line uses must be mapped)")
            continue
        for address, entry in _entries(section, key, problems):
            point = _point(table, address, entry, f"{key}[{address}]", problems)
            if point is not None:
                points.append(point)

    hmi_coils, request, ack = _hmi(raw.get("hmi"), problems)
    hmi = raw.get("hmi")
    setpoints = _setpoints(hmi.get("setpoints") if isinstance(hmi, dict) else None, problems)
    status = _status(raw.get("status"), problems)
    return RegisterMap(points=tuple(points), hmi_coils=hmi_coils, status_registers=status,
                       hmi_request=request, hmi_ack=ack, hmi_setpoints=setpoints), name


def _setpoints(section: object, problems: list[str]) -> tuple[HmiSetpoint, ...]:
    """hmi.setpoints: {name: address}; each name one of the line map's, whose
    default and meaning it keeps (the meaning doesn't move with the address)."""
    if section is None:
        return ()
    if not isinstance(section, dict):
        problems.append("hmi.setpoints: must map each setpoint name to its holding register")
        return ()
    known = {sp.name: sp for sp in LINE_REGISTER_MAP.hmi_setpoints}
    out = []
    for name, address in section.items():
        if name not in known:
            problems.append(f"hmi.setpoints: unknown setpoint {name!r} (known: {sorted(known)})")
        elif not isinstance(address, int) or isinstance(address, bool):
            problems.append(f"hmi.setpoints.{name}: {address!r} is not an integer address")
        else:
            out.append(HmiSetpoint(name, address, known[name].default, known[name].description))
    return tuple(out)


def _entries(section: object, where: str, problems: list[str]) -> list[tuple[int, object]]:
    if not isinstance(section, dict):
        problems.append(f"{where}: must map addresses to entries")
        return []
    out = []
    for address, entry in section.items():
        if not isinstance(address, int) or isinstance(address, bool):
            problems.append(f"{where}: address {address!r} is not an integer")
            continue
        out.append((address, entry))
    return out


def _point(table: str, address: int, entry: object, where: str, problems: list[str]) -> Point | None:
    if table not in ANALOG:
        if not isinstance(entry, str):
            problems.append(f"{where}: a discrete point is just its tag name")
            return None
        return Point(entry, table, address)
    if not isinstance(entry, dict) or set(entry) - {"tag", "scale", "full_scale"} or not {"tag", "scale", "full_scale"} <= set(entry):
        problems.append(f"{where}: an analog point is {{tag, scale, full_scale}}, exactly")
        return None
    try:
        return Point(str(entry["tag"]), table, address, scale=float(entry["scale"]), full_scale=float(entry["full_scale"]))
    except (TypeError, ValueError):
        problems.append(f"{where}: scale and full_scale must be numbers")
        return None


def _hmi(section: object, problems: list[str]) -> tuple[tuple[HmiCoil, ...], int | None, int | None]:
    if section is None:
        problems.append("hmi: missing (the controller needs start/stop/reset/acknowledge)")
        return (), None, None
    if not isinstance(section, dict) or not {"request", "ack", "commands"} <= set(section) <= {
            "request", "ack", "commands", "setpoints"}:
        problems.append("hmi: must have request, ack and commands (and optionally setpoints)")
        return (), None, None
    coils = []
    commands = section["commands"]
    if not isinstance(commands, dict):
        problems.append("hmi.commands: must map each command to its pushbutton coil")
        commands = {}
    for command, address in commands.items():
        if not isinstance(address, int) or isinstance(address, bool):
            problems.append(f"hmi.commands.{command}: address {address!r} is not an integer")
            continue
        coils.append(HmiCoil(str(command), address, _COMMAND_TEXT.get(str(command), "")))
    missing = {"start", "stop", "reset", "acknowledge"} - set(commands)
    if missing:
        problems.append(f"hmi.commands: missing {sorted(missing)}")
    words = []
    for key in ("request", "ack"):
        value = section[key]
        if not isinstance(value, int) or isinstance(value, bool):
            problems.append(f"hmi.{key}: {value!r} is not an integer address")
            value = None
        words.append(value)
    return tuple(coils), words[0], words[1]


def _status(section: object, problems: list[str]) -> tuple[StatusRegister, ...]:
    if section is None:
        return ()
    if not isinstance(section, dict):
        problems.append("status: must map each status register name to its address")
        return ()
    unknown = set(section) - set(STATUS_NAMES)
    missing = set(STATUS_NAMES) - set(section)
    if unknown:
        problems.append(f"status: unknown register(s) {sorted(unknown)} (known: {list(STATUS_NAMES)})")
    if missing:
        problems.append(f"status: all {len(STATUS_NAMES)} registers or none -- missing {sorted(missing)}")
    out = []
    for name in STATUS_NAMES:
        address = section.get(name)
        if name in section and (not isinstance(address, int) or isinstance(address, bool)):
            problems.append(f"status.{name}: {address!r} is not an integer address")
        elif name in section:
            out.append(StatusRegister(name, address, _STATUS_TEXT[name]))
    return tuple(out)
