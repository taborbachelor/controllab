"""Binds an IOImage to Modbus (docs/CONTROL-LAB.md §10, Phase 7 steps 2-4):
which tag lives at which address in which table, at what scale, and who
may write it.

Generic, the same way TagHistory is: nothing here knows this line's
tags. services/protocols/line_map.py is the map for the bulk-material
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

**The controller's view must be pollable by a standard PLC master**
(Phase 7 step 4). A PLC polling a remote-I/O device -- OpenPLC's master
is typical -- gets exactly one contiguous start/size range per table,
writes coils with FC 15 every cycle and never reads them, and has one
holding-register read range (FC 3) and a separate write range (FC 16).
validate() therefore requires the controller-facing addresses to form
exactly five contiguous ranges, reported by controller_ranges():

    discrete inputs   read   every DI tag
    input registers   read   every AI tag
    holding (read)    read   the HMI request word
    coils             write  every DO tag -- and nothing else
    holding (write)   write  every AO tag + the status block + the HMI ack word

The step-2/3 map failed this (HMI requests as coils, which a master
can't read; status registers at 200, which no single write range can
reach together with the analog outputs), found when step 4 checked the
map against OpenPLC's polling model. ModbusIOSync -- the reference
external controller's side -- polls in exactly this shape, so every
external-controller test is also a PLC-master compatibility test.

Operator commands, two paths:

- **HMI coils** (any mode): momentary pushbuttons for a SCADA client --
  writing 1 issues the command through `on_command`, writing 0 does
  nothing, they always read back 0. Kept in their own block, apart from
  field I/O, as §3.2 has always specified. Not part of the controller's
  view.
- **The HMI request/ack words** (external-controller mode): how a
  command reaches a controller on the far side of the wire -- see
  HmiHandshake.

Outputs are writable only when `outputs_writable` is set. With
ControlLab's built-in LineController in charge, it rewrites every output
on every scan, so a Modbus write would just fight it; refusing the write
(ILLEGAL_DATA_ADDRESS, the usual answer for a read-only point) is
honest. External-controller mode turns it on.

Controller status registers are holding registers that are NOT I/O-image
tags: the controller publishes its internal state there (see
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


# Non-tag holding registers, identified in the data store by these markers.
_REQUEST = "hmi_request"
_ACK = "hmi_ack"


@dataclass(frozen=True)
class ControllerRanges:
    """The five (start, count) ranges a PLC master configures -- one per
    table, as OpenPLC's "slave device" form asks for them."""

    discrete_inputs: tuple[int, int]
    input_registers: tuple[int, int]
    holding_read: tuple[int, int]
    coils: tuple[int, int]
    holding_write: tuple[int, int]


@dataclass(frozen=True)
class RegisterMap:
    points: tuple[Point, ...]
    hmi_coils: tuple[HmiCoil, ...] = ()
    status_registers: tuple[StatusRegister, ...] = ()
    hmi_request: int | None = None  # holding register the controller reads
    hmi_ack: int | None = None  # holding register the controller writes

    @property
    def commands(self) -> list[str]:
        """HMI commands in bit order for the request/ack words: the HMI
        coils' order by address."""
        return [h.command for h in sorted(self.hmi_coils, key=lambda h: h.address)]

    def validate(self, io: IOImage) -> None:
        """Raises ValueError listing every problem at once."""
        problems: list[str] = []
        seen_tags: dict[str, int] = {}
        taken: dict[tuple[str, int], str] = {}

        def claim(table: str, address: int, what: str) -> None:
            if (table, address) in taken:
                problems.append(f"{what}: {table} {address} already used by {taken[(table, address)]}")
            taken[(table, address)] = what

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
            claim(p.table, p.address, p.tag)

        for h in self.hmi_coils:
            claim(COIL, h.address, f"HMI {h.command}")
        for r in self.status_registers:
            claim(HOLDING_REGISTER, r.address, f"status {r.name}")
        if self.hmi_request is not None:
            claim(HOLDING_REGISTER, self.hmi_request, _REQUEST)
        if self.hmi_ack is not None:
            claim(HOLDING_REGISTER, self.hmi_ack, _ACK)
        if (self.hmi_request is None) != (self.hmi_ack is None):
            problems.append("hmi_request and hmi_ack come as a pair")
        if len(self.hmi_coils) > 16:
            problems.append("more than 16 HMI commands don't fit a request word")

        problems += [f"{tag}: mapped {n} times" for tag, n in seen_tags.items() if n > 1]
        problems += [f"{name}: in the I/O image but not mapped" for name in io.names() if name not in seen_tags]
        try:
            self.controller_ranges()
        except ValueError as e:
            problems.append(str(e))
        if problems:
            raise ValueError("invalid register map:\n  " + "\n  ".join(problems))

    def by_table(self, table: str) -> dict[int, Point]:
        return {p.address: p for p in self.points if p.table == table}

    def controller_ranges(self) -> ControllerRanges:
        """The controller's view as the five contiguous ranges a PLC master
        polls (module docstring). Raises ValueError if any set of
        addresses has a hole -- the map would then be unusable by a
        standard master."""

        def span(addresses: list[int], what: str) -> tuple[int, int]:
            if not addresses:
                return (0, 0)
            lo, hi = min(addresses), max(addresses)
            if hi - lo + 1 != len(set(addresses)):
                raise ValueError(f"{what} {sorted(addresses)} isn't one contiguous range -- a PLC master can't poll it")
            return (lo, hi - lo + 1)

        write = list(self.by_table(HOLDING_REGISTER)) + [r.address for r in self.status_registers]
        if self.hmi_ack is not None:
            write.append(self.hmi_ack)
        return ControllerRanges(
            discrete_inputs=span(list(self.by_table(DISCRETE_INPUT)), "discrete inputs"),
            input_registers=span(list(self.by_table(INPUT_REGISTER)), "input registers"),
            holding_read=span([self.hmi_request] if self.hmi_request is not None else [], "holding read"),
            coils=span(list(self.by_table(COIL)), "output coils"),
            holding_write=span(write, "holding write (analog outputs + status + ack)"),
        )


class HmiHandshake:
    """Operator commands to an external controller, as a 4-phase
    request/acknowledge on two words -- the standard way an HMI hands a
    command to a PLC it can't call directly. Bit i = command i
    (RegisterMap.commands).

      1. ControlLab sets the request bit.
      2. The controller sees request=1, ack=0: it acts, and sets ack.
      3. ControlLab sees ack rise: it clears the request.
      4. The controller sees request=0, ack=1: it clears ack. Idle again.

    Exactly once, including the edge a naive two-phase version gets
    wrong: a new press while the previous ack is still set would be
    cleared by that same ack and lost -- so such a press is held as
    pending and only raised once the ack bit has dropped. A press of a
    command whose request is still up merges with it (one command), as
    two presses between two PLC scans would on real hardware.

    Not thread-safe on its own; only touched under the lock the Modbus
    server holds."""

    def __init__(self, commands: list[str]) -> None:
        self.commands = list(commands)
        self.request_word = 0
        self.ack_word = 0
        self._pending: set[str] = set()

    def _bit(self, command: str) -> int:
        if command not in self.commands:
            raise ValueError(f"unknown HMI command {command!r}")
        return 1 << self.commands.index(command)

    def request(self, command: str) -> None:
        bit = self._bit(command)
        if self.ack_word & bit:
            self._pending.add(command)
        else:
            self.request_word |= bit

    def write_ack(self, value: int) -> None:
        rising = value & ~self.ack_word
        falling = self.ack_word & ~value
        self.ack_word = value
        self.request_word &= ~rising  # step 3
        for command in list(self._pending):
            if falling & self._bit(command):
                self._pending.discard(command)
                self.request_word |= self._bit(command)

    def outstanding(self) -> list[str]:
        """Commands requested but not yet taken by the controller."""
        return [c for c in self.commands if self.request_word & self._bit(c) or c in self._pending]

    def reset(self) -> None:
        self.request_word = self.ack_word = 0
        self._pending.clear()


def to_raw(value: float, scale: float) -> int:
    return max(0, min(UINT16_MAX, round(value * scale)))


class IOImageDataStore:
    """A services.protocols.modbus.DataStore over an IOImage, through a
    RegisterMap. `get_io` is called on every request rather than holding
    an IOImage directly, so whoever owns the plant can replace it (e.g.
    the live dashboard's "New session") without re-creating the server.

    `on_command` receives an HMI coil's command when a client writes 1.
    `handshake` (external-controller mode) backs the request/ack words;
    without one they read 0 and refuse writes. `on_output_write` is
    called after any write of a controller-owned register (a comm-loss
    watchdog's heartbeat)."""

    def __init__(
        self,
        register_map: RegisterMap,
        get_io: Callable[[], IOImage],
        on_command: Callable[[str], None] | None = None,
        outputs_writable: bool = False,
        handshake: HmiHandshake | None = None,
        on_output_write: Callable[[], None] | None = None,
        status_source: Callable[[], list[int]] | None = None,
    ) -> None:
        register_map.validate(get_io())
        self.map = register_map
        self.get_io = get_io
        self.on_command = on_command
        self.outputs_writable = outputs_writable
        self.handshake = handshake
        self.on_output_write = on_output_write
        # Status registers: computed by `status_source` (built-in controller,
        # read-only) or stored here as written by an external controller.
        self.status_source = status_source
        self.status_values = [0] * len(register_map.status_registers)
        self._coils = register_map.by_table(COIL)
        self._discrete = register_map.by_table(DISCRETE_INPUT)
        self._inputs = register_map.by_table(INPUT_REGISTER)
        self._hmi = {h.address: h for h in register_map.hmi_coils}
        # Holding table entries: a Point, a status index (int), or a marker.
        self._holding: dict[int, object] = dict(register_map.by_table(HOLDING_REGISTER))
        self._holding.update({r.address: i for i, r in enumerate(register_map.status_registers)})
        if register_map.hmi_request is not None:
            self._holding[register_map.hmi_request] = _REQUEST
            self._holding[register_map.hmi_ack] = _ACK

    @staticmethod
    def _points(table: dict[int, object], address: int, count: int, what: str) -> list:
        missing = [a for a in range(address, address + count) if a not in table]
        if missing:
            raise ModbusError(ILLEGAL_DATA_ADDRESS, f"no {what} mapped at {missing[0]}")
        return [table[a] for a in range(address, address + count)]

    # ---- reads -------------------------------------------------------------

    def read_coils(self, address: int, count: int) -> list[bool]:
        io = self.get_io()
        targets = self._points({**self._coils, **self._hmi}, address, count, "coil")
        return [False if isinstance(t, HmiCoil) else bool(io.read(t.tag)) for t in targets]

    def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        io = self.get_io()
        return [bool(io.read(p.tag)) for p in self._points(self._discrete, address, count, "discrete input")]

    def read_input_registers(self, address: int, count: int) -> list[int]:
        io = self.get_io()
        return [to_raw(io.read(p.tag), p.scale) for p in self._points(self._inputs, address, count, "input register")]

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        io = self.get_io()
        status = self.status_source() if self.status_source is not None else self.status_values
        out = []
        for t in self._points(self._holding, address, count, "holding register"):
            if t == _REQUEST:
                out.append(self.handshake.request_word if self.handshake else 0)
            elif t == _ACK:
                out.append(self.handshake.ack_word if self.handshake else 0)
            elif isinstance(t, int):
                out.append(status[t])
            else:
                out.append(to_raw(io.read(t.tag), t.scale))
        return out

    # ---- writes --------------------------------------------------------------
    # Validate the whole request before applying any of it, so a refused
    # multi-write never leaves the outputs half-changed.

    def write_coils(self, address: int, values: list[bool]) -> None:
        targets = self._points({**self._coils, **self._hmi}, address, len(values), "coil")
        outputs = [t for t in targets if isinstance(t, Point)]
        if outputs and not self.outputs_writable:
            raise ModbusError(ILLEGAL_DATA_ADDRESS, "outputs are owned by the built-in controller")
        io = self.get_io()
        for target, value in zip(targets, values):
            if isinstance(target, HmiCoil):
                if value and self.on_command is not None:
                    self.on_command(target.command)
            else:
                io.write_output(target.tag, bool(value))
        if outputs and self.on_output_write is not None:
            self.on_output_write()

    def write_holding_registers(self, address: int, values: list[int]) -> None:
        targets = self._points(self._holding, address, len(values), "holding register")
        if not self.outputs_writable:
            raise ModbusError(ILLEGAL_DATA_ADDRESS, "outputs are owned by the built-in controller")
        if _REQUEST in targets:
            raise ModbusError(ILLEGAL_DATA_ADDRESS, "the HMI request word is written by ControlLab, not the controller")
        if _ACK in targets and self.handshake is None:
            raise ModbusError(ILLEGAL_DATA_ADDRESS, "no HMI handshake in this mode")
        if self.status_source is not None and any(isinstance(t, int) and not isinstance(t, bool) for t in targets):
            raise ModbusError(ILLEGAL_DATA_ADDRESS, "status is computed by the built-in controller")
        io = self.get_io()
        for target, raw in zip(targets, values):
            if target == _ACK:
                self.handshake.write_ack(raw)
            elif isinstance(target, int):
                self.status_values[target] = raw
            else:
                io.write_output(target.tag, raw / target.scale)
        if self.on_output_write is not None:
            self.on_output_write()


def render_markdown(register_map: RegisterMap, io: IOImage, title: str, status_notes: str = "") -> str:
    """The register map as a commissioning document -- generated from the
    same RegisterMap the server uses, so the document can't drift from
    what's actually served (a test compares the committed copy)."""
    ref = lambda table, a: f"{MODBUS_REF[table] + a:05d}" if table != COIL else f"{a + 1:05d}"  # noqa: E731
    r = register_map.controller_ranges()
    lines = [
        f"# {title}",
        "",
        "*Generated by `scripts/register_map.py` from `services/protocols/line_map.py` -- do not edit by hand.*",
        "",
        "Modbus TCP, any unit ID. Addresses are 0-based protocol addresses; the Ref column is the conventional "
        "1-based reference (coils 00001, discrete inputs 10001, input registers 30001, holding registers 40001). "
        "Analog values are unsigned 16-bit integers: raw = round(value × scale), clamped to 0..65535.",
        "",
        "## Controller view — PLC master configuration",
        "",
        "Everything a controller needs is five contiguous ranges, one per table — exactly what a PLC master's "
        "remote-I/O device configuration asks for (e.g. OpenPLC's *Slave Devices*: a start address and size "
        "per table).",
        "",
        "| Table | Direction | Start | Size | Contents |",
        "|---|---|---:|---:|---|",
        f"| Discrete inputs (FC 02) | read | {r.discrete_inputs[0]} | {r.discrete_inputs[1]} | field sensors |",
        f"| Input registers (FC 04) | read | {r.input_registers[0]} | {r.input_registers[1]} | analog sensors |",
        f"| Holding registers (FC 03) | read | {r.holding_read[0]} | {r.holding_read[1]} | HMI request word |",
        f"| Coils (FC 15) | write | {r.coils[0]} | {r.coils[1]} | field outputs |",
        f"| Holding registers (FC 16) | write | {r.holding_write[0]} | {r.holding_write[1]} | analog outputs, controller status, HMI ack word |",
        "",
    ]
    sections = [
        (DISCRETE_INPUT, "Discrete inputs (FC 02, read-only)"),
        (INPUT_REGISTER, "Input registers (FC 04, read-only)"),
        (COIL, "Coils — field outputs (FC 01 read; FC 05/15 write in external-controller mode only)"),
    ]
    for table, heading in sections:
        points = sorted((p for p in register_map.points if p.table == table), key=lambda p: p.address)
        analog = table == INPUT_REGISTER
        lines += [f"## {heading}", ""]
        if analog:
            lines += ["| Address | Ref | Tag | Description | Units | Scale | Full scale → raw |", "|---:|---:|---|---|---|---:|---:|"]
        else:
            lines += ["| Address | Ref | Tag | Description |", "|---:|---:|---|---|"]
        for p in points:
            tag = io.tag(p.tag)
            row = f"| {p.address} | {ref(table, p.address)} | `{p.tag}` | {tag.description} |"
            if analog:
                row += f" {tag.units} | ×{p.scale:g} | {p.full_scale:g} → {to_raw(p.full_scale, p.scale)} |"
            lines.append(row)
        lines.append("")

    lines += [
        "## Holding registers",
        "",
        "Written by the controller in external-controller mode (FC 16); read-only with the built-in controller, "
        "which computes the status block on read.",
        "",
        "| Address | Ref | Name | Description | Units | Scale |",
        "|---:|---:|---|---|---|---:|",
    ]
    rows: list[tuple[int, str]] = []
    for p in register_map.by_table(HOLDING_REGISTER).values():
        tag = io.tag(p.tag)
        rows.append((p.address, f"| {p.address} | {ref(HOLDING_REGISTER, p.address)} | `{p.tag}` | {tag.description} | {tag.units} | ×{p.scale:g} |"))
    for s in register_map.status_registers:
        rows.append((s.address, f"| {s.address} | {ref(HOLDING_REGISTER, s.address)} | `{s.name}` | {s.description} | | |"))
    if register_map.hmi_ack is not None:
        a, q = register_map.hmi_ack, register_map.hmi_request
        rows.append((a, f"| {a} | {ref(HOLDING_REGISTER, a)} | `hmi_ack` | HMI acknowledge word (controller → ControlLab) | | |"))
        rows.append((q, f"| {q} | {ref(HOLDING_REGISTER, q)} | `hmi_request` | HMI request word (ControlLab → controller; read-only to clients) | | |"))
    lines += [row for _, row in sorted(rows)] + [""]

    if register_map.hmi_request is not None:
        bits = ", ".join(f"bit {i} = `{c}`" for i, c in enumerate(register_map.commands))
        lines += [
            "## HMI commands to an external controller — request/acknowledge",
            "",
            f"Bits of `hmi_request` / `hmi_ack`: {bits}. A 4-phase handshake, so each command is taken exactly once:",
            "",
            "1. ControlLab sets the request bit.",
            "2. The controller sees request = 1, ack = 0: it executes the command and sets the ack bit.",
            "3. ControlLab sees the ack bit rise and clears the request bit.",
            "4. The controller sees request = 0, ack = 1 and clears the ack bit.",
            "",
            "A command pressed while its previous ack is still set is held and raised after the ack drops, never lost.",
            "",
        ]
    if register_map.hmi_coils:
        lines += [
            "## Coils — HMI pushbuttons for SCADA clients (FC 05/15 write, momentary)",
            "",
            "Kept apart from field I/O and outside the controller view: writing 1 issues the command once (in "
            "external-controller mode, as a request through the handshake above); writing 0 does nothing; they "
            "always read back 0.",
            "",
            "| Address | Ref | Command | Description |",
            "|---:|---:|---|---|",
        ]
        for h in sorted(register_map.hmi_coils, key=lambda h: h.address):
            lines.append(f"| {h.address} | {ref(COIL, h.address)} | `{h.command}` | {h.description} |")
        lines.append("")
    if status_notes:
        lines += ["## Controller status codes", "", status_notes]
    return "\n".join(lines)


class ModbusIOSync:
    """The controller side of the register map: keeps a *local* IOImage in
    step with a remote one over Modbus, so a controller written against
    IOImage -- LineController, unchanged -- can run in another process.

    **Polls exactly like a standard PLC master** (Phase 7 step 4): per
    scan, one FC 02 (discrete inputs), one FC 04 (input registers), one
    FC 03 (the HMI request word) -- then the controller's scan -- then one
    FC 15 (all output coils) and one FC 16 (analog outputs + status + ack).
    Five requests, each a single contiguous range from
    RegisterMap.controller_ranges(). So anything this class can drive, an
    OpenPLC program configured with those ranges can drive too.

    Inputs are written into the local image with write_input() and
    outputs read from it, so IOImage's own direction rules still hold on
    this side of the wire. `client` is anything with ModbusClient's
    methods (services/protocols/modbus.py)."""

    def __init__(self, client, register_map: RegisterMap, io: IOImage) -> None:
        register_map.validate(io)
        self.client = client
        self.io = io
        self.map = register_map
        self.ranges = register_map.controller_ranges()
        self._ack = 0
        self._holding_write: dict[int, object] = dict(register_map.by_table(HOLDING_REGISTER))
        self._holding_write.update({r.address: i for i, r in enumerate(register_map.status_registers)})
        if register_map.hmi_ack is not None:
            self._holding_write[register_map.hmi_ack] = _ACK

    def pull_inputs(self) -> None:
        start, count = self.ranges.discrete_inputs
        if count:
            points = self.map.by_table(DISCRETE_INPUT)
            for offset, value in enumerate(self.client.read_discrete_inputs(start, count)):
                self.io.write_input(points[start + offset].tag, bool(value))
        start, count = self.ranges.input_registers
        if count:
            points = self.map.by_table(INPUT_REGISTER)
            for offset, raw in enumerate(self.client.read_input_registers(start, count)):
                p = points[start + offset]
                self.io.write_input(p.tag, raw / p.scale)

    def take_commands(self) -> list[str]:
        """Steps 2 and 4 of the HmiHandshake: the commands newly requested
        this scan (to execute now); the ack word goes out with
        push_outputs()."""
        if self.map.hmi_request is None:
            return []
        request = self.client.read_holding_registers(self.map.hmi_request, 1)[0]
        taken = []
        for i, command in enumerate(self.map.commands):
            bit = 1 << i
            if request & bit and not self._ack & bit:
                taken.append(command)
                self._ack |= bit
            elif not request & bit and self._ack & bit:
                self._ack &= ~bit
        return taken

    def push_outputs(self, status: list[int] | None = None) -> None:
        """All outputs in two writes: every output coil (FC 15), then the
        whole holding write range (FC 16) -- analog outputs, the status
        block (`status`, controller_status.encode(); zeros if None), and
        the HMI ack word."""
        start, count = self.ranges.coils
        if count:
            points = self.map.by_table(COIL)
            self.client.write_coils(start, [bool(self.io.read(points[a].tag)) for a in range(start, start + count)])
        start, count = self.ranges.holding_write
        if count:
            values = []
            for a in range(start, start + count):
                t = self._holding_write[a]
                if t == _ACK:
                    values.append(self._ack)
                elif isinstance(t, int):
                    values.append(status[t] if status is not None else 0)
                else:
                    values.append(to_raw(self.io.read(t.tag), t.scale))
            self.client.write_registers(start, values)

    def read_status(self) -> list[int]:
        """The status block as currently published -- the observer side.
        One read spanning the block, then picked out by address: the status
        registers needn't be adjacent (start_inhibit was appended after the
        HMI ack word), only inside the contiguous holding write range."""
        addresses = [r.address for r in self.map.status_registers]
        if not addresses:
            return []
        lo = min(addresses)
        values = self.client.read_holding_registers(lo, max(addresses) - lo + 1)
        return [values[a - lo] for a in addresses]
