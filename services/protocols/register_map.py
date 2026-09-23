"""Binds an IOImage to Modbus (docs/CONTROL-LAB.md §10, Phase 7 step 2):
which tag lives at which address in which table, at what scale, and who
may write it.

Generic, the same way TagHistory is: nothing here knows this line's
tags. A RegisterMap is a list of Points plus a block of HMI command
coils; services/protocols/line_map.py is the one for the bulk-material
line. validate() checks a map against an IOImage before anything is
served -- a register map is a commissioning contract, and a gap or a
collision in it should fail at startup, not show up as a wrong reading
on a PLC.

Mapping rules (confirmed at Phase 7 scoping):

- Each tag type lives in its natural table: DI -> discrete input,
  DO -> coil, AI -> input register, AO -> holding register. So sensor
  values are read-only over Modbus *by construction*: the two input
  tables have no write function codes at all.
- Analog values are scaled unsigned 16-bit integers:
  raw = round(value * scale), and value = raw / scale on the way in.
  validate() requires each analog point's full-scale value to fit in
  0..65535. A reading outside that range at runtime is clamped (a real
  transmitter saturates at its range limits too) rather than wrapped.
- HMI command coils live in their own address block, apart from field
  I/O, as §3.2 has always specified, in one of two modes depending on
  who runs Control:
  * **momentary** (built-in controller, step 2): writing 1 issues the
    command through a callback -- this module never touches Control --
    writing 0 does nothing, and they always read back 0.
  * **latched** (external controller, step 3): an `HmiLatches` object
    holds a request bit per command. ControlLab (the dashboard, a
    scenario) sets it; the external controller reads it, acts on it,
    and writes 0 to clear it -- the standard HMI-to-PLC request/
    acknowledge handshake, so a request is neither lost between two
    controller scans nor acted on twice.

Outputs (the DO coils and AO holding registers) are writable only when
`outputs_writable` is set. With ControlLab's built-in LineController in
charge, it rewrites every output on every scan, so a Modbus write would
just fight it; refusing the write (ILLEGAL_DATA_ADDRESS, the usual answer
for a read-only point) is honest. External-controller mode (Phase 7 step
3) turns it on, because then the remote controller owns the outputs.

Controller status registers (Phase 7 step 3b) are a small block of
holding registers that are NOT I/O-image tags: the controller publishes
its internal state there (line state, fault reason, alarm board -- see
services/protocols/controller_status.py). With the built-in controller
they're computed on read (`status_source`) and read-only; in
external-controller mode the remote controller writes them.

Reads that span an unmapped address are refused whole with
ILLEGAL_DATA_ADDRESS rather than padded with zeros -- a PLC reading
"0" from a hole in the map would be a silent wrong value.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from services.protocols.modbus import ILLEGAL_DATA_ADDRESS, ModbusError
from services.simulation.engine.io_image import IOImage, TagType

COIL = "coil"
DISCRETE_INPUT = "discrete_input"
INPUT_REGISTER = "input_register"
HOLDING_REGISTER = "holding_register"

TABLE_FOR_TYPE = {
    TagType.DO: COIL,
    TagType.DI: DISCRETE_INPUT,
    TagType.AI: INPUT_REGISTER,
    TagType.AO: HOLDING_REGISTER,
}
MODBUS_REF = {COIL: 0, DISCRETE_INPUT: 10001, INPUT_REGISTER: 30001, HOLDING_REGISTER: 40001}
UINT16_MAX = 0xFFFF


@dataclass(frozen=True)
class Point:
    tag: str
    table: str
    address: int
    scale: float = 1.0  # analog only: raw = round(value * scale)
    full_scale: float = 0.0  # analog only: the largest engineering value the point must carry


@dataclass(frozen=True)
class HmiCoil:
    command: str
    address: int
    description: str = ""


@dataclass(frozen=True)
class StatusRegister:
    name: str
    address: int  # a holding register
    description: str = ""


@dataclass(frozen=True)
class RegisterMap:
    points: tuple[Point, ...]
    hmi_coils: tuple[HmiCoil, ...] = ()
    status_registers: tuple[StatusRegister, ...] = ()

    def validate(self, io: IOImage) -> None:
        """Raises ValueError listing every problem at once."""
        problems: list[str] = []
        seen_tags: dict[str, int] = {}
        taken: dict[tuple[str, int], str] = {}

        for p in self.points:
            seen_tags[p.tag] = seen_tags.get(p.tag, 0) + 1
            if p.tag not in io:
                problems.append(f"{p.tag}: not a tag in this I/O image")
                continue
            expected = TABLE_FOR_TYPE[io.tag(p.tag).type]
            if p.table != expected:
                problems.append(f"{p.tag}: {io.tag(p.tag).type.name} belongs in {expected}, not {p.table}")
            if not 0 <= p.address <= UINT16_MAX:
                problems.append(f"{p.tag}: address {p.address} outside 0..65535")
            if p.table in (INPUT_REGISTER, HOLDING_REGISTER):
                if p.scale <= 0:
                    problems.append(f"{p.tag}: scale must be positive")
                elif round(p.full_scale * p.scale) > UINT16_MAX:
                    problems.append(f"{p.tag}: full scale {p.full_scale} x {p.scale} doesn't fit in 16 bits")
            key = (p.table, p.address)
            if key in taken:
                problems.append(f"{p.tag}: {p.table} {p.address} already used by {taken[key]}")
            taken[key] = p.tag

        for h in self.hmi_coils:
            key = (COIL, h.address)
            if key in taken:
                problems.append(f"HMI {h.command}: coil {h.address} already used by {taken[key]}")
            taken[key] = f"HMI {h.command}"

        for r in self.status_registers:
            key = (HOLDING_REGISTER, r.address)
            if key in taken:
                problems.append(f"status {r.name}: holding register {r.address} already used by {taken[key]}")
            taken[key] = f"status {r.name}"

        problems += [f"{tag}: mapped {n} times" for tag, n in seen_tags.items() if n > 1]
        problems += [f"{name}: in the I/O image but not mapped" for name in io.names() if name not in seen_tags]
        if problems:
            raise ValueError("invalid register map:\n  " + "\n  ".join(problems))

    def by_table(self, table: str) -> dict[int, Point]:
        return {p.address: p for p in self.points if p.table == table}


class HmiLatches:
    """Request bits for the latched HMI handshake (see the module
    docstring). Not thread-safe on its own -- it's only touched under the
    same lock the Modbus server holds."""

    def __init__(self, commands: list[str]) -> None:
        self.requested = {c: False for c in commands}

    def request(self, command: str) -> None:
        if command not in self.requested:
            raise ValueError(f"unknown HMI command {command!r}")
        self.requested[command] = True


def to_raw(value: float, scale: float) -> int:
    return max(0, min(UINT16_MAX, round(value * scale)))


class IOImageDataStore:
    """A services.protocols.modbus.DataStore over an IOImage, through a
    RegisterMap. `get_io` is called on every request rather than holding
    an IOImage directly, so whoever owns the plant can replace it (e.g.
    the live dashboard's "New session") without re-creating the server.
    `on_command` receives an HMI coil's command name when a client writes
    1 to it."""

    def __init__(
        self,
        register_map: RegisterMap,
        get_io: Callable[[], IOImage],
        on_command: Callable[[str], None] | None = None,
        outputs_writable: bool = False,
        hmi_latches: HmiLatches | None = None,
        on_output_write: Callable[[], None] | None = None,
        status_source: Callable[[], list[int]] | None = None,
    ) -> None:
        """Pass `hmi_latches` for the latched handshake (external
        controller); otherwise HMI coils are momentary and call
        `on_command`."""
        register_map.validate(get_io())
        self.hmi_latches = hmi_latches
        self.on_output_write = on_output_write  # e.g. a comm-loss watchdog heartbeat
        # Status registers: computed by `status_source` (built-in controller,
        # read-only) or stored here as written by an external controller.
        self.status_source = status_source
        self._status_addr = {r.address: i for i, r in enumerate(register_map.status_registers)}
        self.status_values = [0] * len(register_map.status_registers)
        self.map = register_map
        self.get_io = get_io
        self.on_command = on_command
        self.outputs_writable = outputs_writable
        self._coils = register_map.by_table(COIL)
        self._discrete = register_map.by_table(DISCRETE_INPUT)
        self._inputs = register_map.by_table(INPUT_REGISTER)
        self._holding = register_map.by_table(HOLDING_REGISTER)
        self._hmi = {h.address: h for h in register_map.hmi_coils}

    @staticmethod
    def _points(table: dict[int, object], address: int, count: int, what: str) -> list:
        missing = [a for a in range(address, address + count) if a not in table]
        if missing:
            raise ModbusError(ILLEGAL_DATA_ADDRESS, f"no {what} mapped at {missing[0]}")
        return [table[a] for a in range(address, address + count)]

    # ---- reads -------------------------------------------------------------

    def read_coils(self, address: int, count: int) -> list[bool]:
        io = self.get_io()
        table = {**self._coils, **self._hmi}
        return [self._read_hmi(p) if isinstance(p, HmiCoil) else bool(io.read(p.tag)) for p in self._points(table, address, count, "coil")]

    def _read_hmi(self, coil: HmiCoil) -> bool:
        return self.hmi_latches.requested[coil.command] if self.hmi_latches is not None else False

    def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        io = self.get_io()
        return [bool(io.read(p.tag)) for p in self._points(self._discrete, address, count, "discrete input")]

    def read_input_registers(self, address: int, count: int) -> list[int]:
        io = self.get_io()
        return [to_raw(io.read(p.tag), p.scale) for p in self._points(self._inputs, address, count, "input register")]

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        io = self.get_io()
        table = {**self._holding, **self._status_addr}
        status = self.status_source() if self.status_source is not None else self.status_values
        return [
            status[p] if isinstance(p, int) else to_raw(io.read(p.tag), p.scale)
            for p in self._points(table, address, count, "holding register")
        ]

    # ---- writes --------------------------------------------------------------
    # Validate the whole request before applying any of it, so a refused
    # multi-write never leaves the outputs half-changed.

    def write_coils(self, address: int, values: list[bool]) -> None:
        table = {**self._coils, **self._hmi}
        targets = self._points(table, address, len(values), "coil")
        if not self.outputs_writable and any(isinstance(t, Point) for t in targets):
            raise ModbusError(ILLEGAL_DATA_ADDRESS, "outputs are owned by the built-in controller")
        io = self.get_io()
        for target, value in zip(targets, values):
            if isinstance(target, HmiCoil):
                if self.hmi_latches is not None:
                    self.hmi_latches.requested[target.command] = bool(value)  # 1 = request, 0 = acknowledge
                elif value and self.on_command is not None:
                    self.on_command(target.command)
            else:
                io.write_output(target.tag, bool(value))
        if self.on_output_write is not None and any(isinstance(t, Point) for t in targets):
            self.on_output_write()

    def write_holding_registers(self, address: int, values: list[int]) -> None:
        targets = self._points({**self._holding, **self._status_addr}, address, len(values), "holding register")
        if not self.outputs_writable or (self.status_source is not None and any(isinstance(t, int) for t in targets)):
            raise ModbusError(ILLEGAL_DATA_ADDRESS, "outputs are owned by the built-in controller")
        io = self.get_io()
        for target, raw in zip(targets, values):
            if isinstance(target, int):
                self.status_values[target] = raw
            else:
                io.write_output(target.tag, raw / target.scale)
        if self.on_output_write is not None and any(isinstance(t, Point) for t in targets):
            self.on_output_write()


def render_markdown(register_map: RegisterMap, io: IOImage, title: str, status_notes: str = "") -> str:
    """The register map as a commissioning document -- generated from the
    same RegisterMap the server uses, so the document can't drift from
    what's actually served (a test compares the committed copy)."""
    lines = [
        f"# {title}",
        "",
        "*Generated by `scripts/register_map.py` from `services/protocols/line_map.py` -- do not edit by hand.*",
        "",
        "Modbus TCP, any unit ID. Addresses are 0-based protocol addresses; the Ref column is the conventional "
        "1-based reference (coils 00001, discrete inputs 10001, input registers 30001, holding registers 40001). "
        "Analog values are unsigned 16-bit integers: raw = round(value × scale), clamped to 0..65535.",
        "",
    ]
    sections = [
        (DISCRETE_INPUT, "Discrete inputs (FC 02, read-only)"),
        (INPUT_REGISTER, "Input registers (FC 04, read-only)"),
        (COIL, "Coils — field outputs (FC 01 read; FC 05/15 write in external-controller mode only)"),
        (HOLDING_REGISTER, "Holding registers — analog outputs (FC 03 read; FC 06/16 write in external-controller mode only)"),
    ]
    for table, heading in sections:
        points = sorted((p for p in register_map.points if p.table == table), key=lambda p: p.address)
        analog = table in (INPUT_REGISTER, HOLDING_REGISTER)
        lines += [f"## {heading}", ""]
        if analog:
            lines += ["| Address | Ref | Tag | Description | Units | Scale | Full scale → raw |", "|---:|---:|---|---|---|---:|---:|"]
        else:
            lines += ["| Address | Ref | Tag | Description |", "|---:|---:|---|---|"]
        for p in points:
            tag = io.tag(p.tag)
            ref = f"{MODBUS_REF[table] + p.address:05d}" if table != COIL else f"{p.address + 1:05d}"
            row = f"| {p.address} | {ref} | `{p.tag}` | {tag.description} |"
            if analog:
                row += f" {tag.units} | ×{p.scale:g} | {p.full_scale:g} → {to_raw(p.full_scale, p.scale)} |"
            lines.append(row)
        lines.append("")
    if register_map.hmi_coils:
        lines += [
            "## Coils — HMI commands (FC 05/15 write, momentary)",
            "",
            "Pushbuttons, kept apart from field I/O: writing 1 issues the command once; writing 0 does nothing; they always read back 0.",
            "",
            "| Address | Ref | Command | Description |",
            "|---:|---:|---|---|",
        ]
        for h in sorted(register_map.hmi_coils, key=lambda h: h.address):
            lines.append(f"| {h.address} | {h.address + 1:05d} | `{h.command}` | {h.description} |")
        lines.append("")
        lines += [
            "In external-controller mode these are **latched requests** instead: ControlLab sets the bit, the "
            "controller acts on it and writes 0 to acknowledge.",
            "",
        ]
    if register_map.status_registers:
        lines += [
            "## Holding registers — controller status (FC 03 read; written by the controller)",
            "",
            "The controller's internal state, published every scan like a PLC's HMI status words. With the "
            "built-in controller they are computed on read and read-only; in external-controller mode the "
            "external controller writes them (FC 16).",
            "",
            "| Address | Ref | Name | Description |",
            "|---:|---:|---|---|",
        ]
        for r in register_map.status_registers:
            lines.append(f"| {r.address} | {MODBUS_REF[HOLDING_REGISTER] + r.address:05d} | `{r.name}` | {r.description} |")
        lines.append("")
        if status_notes:
            lines.append(status_notes)
    return "\n".join(lines)


def contiguous_runs(addresses: list[int]) -> list[tuple[int, int]]:
    """[(start, count), ...] covering sorted `addresses` in as few Modbus
    requests as possible without ever spanning an unmapped hole (which
    IOImageDataStore refuses, and a strict PLC would too)."""
    runs: list[tuple[int, int]] = []
    for a in sorted(addresses):
        if runs and runs[-1][0] + runs[-1][1] == a:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((a, 1))
    return runs


class ModbusIOSync:
    """The controller side of the register map (Phase 7 step 3): keeps a
    *local* IOImage in step with a remote one over Modbus, so a controller
    written against IOImage -- LineController, unchanged -- can run in a
    different process from the plant.

    Each controller scan is: pull_inputs() (sensors in), take_commands()
    (latched HMI requests in, and acknowledged), the controller's own
    scan, push_outputs() (outputs out). Inputs are written into the local
    image with write_input() and outputs read from it, so IOImage's own
    direction rules still hold on this side of the wire too.

    `client` is anything with ModbusClient's methods (services/protocols/
    modbus.py)."""

    def __init__(self, client, register_map: RegisterMap, io: IOImage) -> None:
        register_map.validate(io)
        self.client = client
        self.io = io
        self.map = register_map
        self._runs = {
            table: [(start, count, register_map.by_table(table)) for start, count in contiguous_runs(list(register_map.by_table(table)))]
            for table in (DISCRETE_INPUT, INPUT_REGISTER, COIL, HOLDING_REGISTER)
        }
        self._hmi = sorted(register_map.hmi_coils, key=lambda h: h.address)

    def pull_inputs(self) -> None:
        for start, count, points in self._runs[DISCRETE_INPUT]:
            for offset, value in enumerate(self.client.read_discrete_inputs(start, count)):
                self.io.write_input(points[start + offset].tag, bool(value))
        for start, count, points in self._runs[INPUT_REGISTER]:
            for offset, raw in enumerate(self.client.read_input_registers(start, count)):
                p = points[start + offset]
                self.io.write_input(p.tag, raw / p.scale)

    def take_commands(self) -> list[str]:
        """The HMI requests currently latched, in address order --
        acknowledged (written back to 0) before returning, so each
        request is acted on exactly once."""
        taken: list[str] = []
        for start, count in contiguous_runs([h.address for h in self._hmi]):
            bits = self.client.read_coils(start, count)
            by_address = {h.address: h for h in self._hmi}
            for offset, bit in enumerate(bits):
                if bit:
                    coil = by_address[start + offset]
                    self.client.write_coil(coil.address, False)
                    taken.append(coil.command)
        return taken

    def push_status(self, values: list[int]) -> None:
        """Publish the controller status block (controller_status.encode())."""
        for start, count in contiguous_runs([r.address for r in self.map.status_registers]):
            offset = [r.address for r in self.map.status_registers].index(start)
            self.client.write_registers(start, values[offset : offset + count])

    def read_status(self) -> list[int]:
        """The status block as currently published -- the observer side."""
        out: list[int] = []
        for start, count in contiguous_runs([r.address for r in self.map.status_registers]):
            out += self.client.read_holding_registers(start, count)
        return out

    def push_outputs(self) -> None:
        for start, count, points in self._runs[COIL]:
            self.client.write_coils(start, [bool(self.io.read(points[a].tag)) for a in range(start, start + count)])
        for start, count, points in self._runs[HOLDING_REGISTER]:
            self.client.write_registers(start, [to_raw(self.io.read(points[a].tag), points[a].scale) for a in range(start, start + count)])
