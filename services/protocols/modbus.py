"""A minimal Modbus TCP server (docs/CONTROL-LAB.md §10, Phase 7 step 1).

Stdlib only, zero runtime dependencies -- confirmed at Phase 7 scoping:
the subset a PLC needs to talk to a plant's I/O is small, and owning it
keeps ControlLab's runtime free of a library whose API has broken
repeatedly across its 3.x line. The condition for hand-rolling a protocol
is proving it interoperates, so tests/integration/test_modbus_interop.py
drives this server with pymodbus's client (a dev-only dependency).

Implements Modbus Application Protocol v1.1b3 over TCP:

    FC 01 Read Coils                 FC 05 Write Single Coil
    FC 02 Read Discrete Inputs       FC 06 Write Single Register
    FC 03 Read Holding Registers     FC 15 Write Multiple Coils
    FC 04 Read Input Registers       FC 16 Write Multiple Registers

plus the standard exception responses (01 illegal function, 02 illegal
data address, 03 illegal data value, 04 server device failure). Nothing
else -- no diagnostics, no file records, no serial framings.

Three layers, each testable on its own:

- **DataStore** -- the four Modbus tables, as a small interface. This
  module knows nothing about ControlLab's I/O image; MemoryDataStore is a
  plain in-memory implementation for tests, and Phase 7 step 2 adds the
  one bound to an IOImage through the register map.
- **handle_pdu() / handle_adu()** -- pure functions, bytes in and bytes
  out. All protocol validation lives here: quantity limits, byte counts,
  address ranges, coil ON/OFF encoding.
- **ModbusServer** -- a stdlib ThreadingTCPServer that reads MBAP frames
  off a socket and calls handle_adu() under a caller-supplied lock, the
  same lock whatever else touches the store (e.g. the simulation's tick
  loop) holds, so a request never observes a half-applied scan.

Unit identifier: accepted and echoed, never checked. On Modbus TCP the
connection already addresses the device; the unit ID only matters behind
a serial gateway, and a single simulated plant has one device.

Security: Modbus has no authentication by design. ModbusServer binds
127.0.0.1 unless told otherwise; exposing it on a network is an explicit
choice for the caller to make.
"""
from __future__ import annotations

import os
import socketserver
import struct
import threading
from typing import Protocol

# Exception codes (Modbus Application Protocol v1.1b3, section 7).
ILLEGAL_FUNCTION = 0x01
ILLEGAL_DATA_ADDRESS = 0x02
ILLEGAL_DATA_VALUE = 0x03
SERVER_DEVICE_FAILURE = 0x04

# Per-request quantity limits from the spec -- they keep a response
# inside the 253-byte PDU limit, so they're protocol rules, not tuning.
MAX_READ_BITS = 2000
MAX_READ_REGISTERS = 125
MAX_WRITE_BITS = 1968
MAX_WRITE_REGISTERS = 123

MBAP_HEADER_LEN = 7  # transaction id (2), protocol id (2), length (2), unit id (1)
MAX_ADU_LEN = 260


class ModbusError(Exception):
    """Raised by a DataStore (or the PDU layer) to produce an exception
    response. `code` is one of the exception codes above."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(message or f"Modbus exception {code:#04x}")
        self.code = code


class DataStore(Protocol):
    """The four Modbus tables. Addresses are 0-based protocol addresses
    (what goes on the wire), not the 1-based "40001"-style reference
    numbers. Implementations raise ModbusError(ILLEGAL_DATA_ADDRESS) for a
    range they don't cover, and ModbusError(ILLEGAL_DATA_VALUE) for a
    value they won't accept."""

    def read_coils(self, address: int, count: int) -> list[bool]: ...
    def read_discrete_inputs(self, address: int, count: int) -> list[bool]: ...
    def read_holding_registers(self, address: int, count: int) -> list[int]: ...
    def read_input_registers(self, address: int, count: int) -> list[int]: ...
    def write_coils(self, address: int, values: list[bool]) -> None: ...
    def write_holding_registers(self, address: int, values: list[int]) -> None: ...


class MemoryDataStore:
    """Fixed-size in-memory tables -- for tests and as the reference
    behavior of a DataStore. Out-of-range access is ILLEGAL_DATA_ADDRESS."""

    def __init__(self, coils: int = 0, discrete_inputs: int = 0, holding_registers: int = 0, input_registers: int = 0) -> None:
        self.coils = [False] * coils
        self.discrete_inputs = [False] * discrete_inputs
        self.holding_registers = [0] * holding_registers
        self.input_registers = [0] * input_registers

    @staticmethod
    def _span(table: list, address: int, count: int) -> slice:
        if address < 0 or address + count > len(table):
            raise ModbusError(ILLEGAL_DATA_ADDRESS, f"address {address}+{count} outside 0..{len(table) - 1}")
        return slice(address, address + count)

    def read_coils(self, address: int, count: int) -> list[bool]:
        return self.coils[self._span(self.coils, address, count)]

    def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        return self.discrete_inputs[self._span(self.discrete_inputs, address, count)]

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        return self.holding_registers[self._span(self.holding_registers, address, count)]

    def read_input_registers(self, address: int, count: int) -> list[int]:
        return self.input_registers[self._span(self.input_registers, address, count)]

    def write_coils(self, address: int, values: list[bool]) -> None:
        self.coils[self._span(self.coils, address, len(values))] = values

    def write_holding_registers(self, address: int, values: list[int]) -> None:
        self.holding_registers[self._span(self.holding_registers, address, len(values))] = values


# ---- bit packing (coils/discrete inputs: LSB of the first byte first) ----

def pack_bits(bits: list[bool]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)
    for i, bit in enumerate(bits):
        if bit:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


def unpack_bits(data: bytes, count: int) -> list[bool]:
    return [bool(data[i // 8] >> (i % 8) & 1) for i in range(count)]


# ---- the PDU layer ----------------------------------------------------------

def _exception(function: int, code: int) -> bytes:
    return bytes((function | 0x80, code))


def _check_quantity(count: int, limit: int) -> None:
    if not 1 <= count <= limit:
        raise ModbusError(ILLEGAL_DATA_VALUE, f"quantity {count} outside 1..{limit}")


def handle_pdu(store: DataStore, pdu: bytes) -> bytes:
    """One request PDU in, one response PDU out -- a normal response or an
    exception response, never a Python exception. A store failing in some
    way it didn't declare maps to SERVER_DEVICE_FAILURE rather than
    dropping the connection, which is what a real device would do."""
    if not pdu:
        return _exception(0, ILLEGAL_FUNCTION)
    function = pdu[0]
    try:
        return _dispatch(store, function, pdu[1:])
    except ModbusError as e:
        return _exception(function, e.code)
    except Exception:  # noqa: BLE001 -- a device answers, it doesn't crash
        return _exception(function, SERVER_DEVICE_FAILURE)


def _fields(body: bytes, fmt: str, exact: bool = True) -> tuple:
    """Unpacks a request's fixed fields, rejecting a wrong-length body as
    ILLEGAL_DATA_VALUE (a malformed request) -- validated here, up front,
    so a struct.error anywhere later can only mean a server-side bug and
    correctly surfaces as SERVER_DEVICE_FAILURE instead."""
    size = struct.calcsize(fmt)
    if len(body) < size or (exact and len(body) != size):
        raise ModbusError(ILLEGAL_DATA_VALUE, "malformed request")
    return struct.unpack(fmt, body[:size])


def _dispatch(store: DataStore, function: int, body: bytes) -> bytes:
    if function in (0x01, 0x02):
        address, count = _fields(body, ">HH")
        _check_quantity(count, MAX_READ_BITS)
        read = store.read_coils if function == 0x01 else store.read_discrete_inputs
        data = pack_bits(read(address, count))
        return bytes((function, len(data))) + data

    if function in (0x03, 0x04):
        address, count = _fields(body, ">HH")
        _check_quantity(count, MAX_READ_REGISTERS)
        read = store.read_holding_registers if function == 0x03 else store.read_input_registers
        values = read(address, count)
        return bytes((function, 2 * count)) + struct.pack(f">{count}H", *values)

    if function == 0x05:
        address, value = _fields(body, ">HH")
        if value not in (0xFF00, 0x0000):
            raise ModbusError(ILLEGAL_DATA_VALUE, "single coil value must be 0xFF00 or 0x0000")
        store.write_coils(address, [value == 0xFF00])
        return bytes((function,)) + body[:4]  # the response echoes the request

    if function == 0x06:
        address, value = _fields(body, ">HH")
        store.write_holding_registers(address, [value])
        return bytes((function,)) + body[:4]

    if function == 0x0F:
        address, count, byte_count = _fields(body, ">HHB", exact=False)
        _check_quantity(count, MAX_WRITE_BITS)
        if byte_count != (count + 7) // 8 or len(body) - 5 != byte_count:
            raise ModbusError(ILLEGAL_DATA_VALUE, "byte count doesn't match quantity")
        store.write_coils(address, unpack_bits(body[5:], count))
        return struct.pack(">BHH", function, address, count)

    if function == 0x10:
        address, count, byte_count = _fields(body, ">HHB", exact=False)
        _check_quantity(count, MAX_WRITE_REGISTERS)
        if byte_count != 2 * count or len(body) - 5 != byte_count:
            raise ModbusError(ILLEGAL_DATA_VALUE, "byte count doesn't match quantity")
        store.write_holding_registers(address, list(struct.unpack(f">{count}H", body[5:])))
        return struct.pack(">BHH", function, address, count)

    raise ModbusError(ILLEGAL_FUNCTION, f"function {function:#04x} not supported")


# ---- the ADU (MBAP) layer ----------------------------------------------------

def handle_adu(store: DataStore, frame: bytes) -> bytes | None:
    """One complete Modbus TCP frame in, the response frame out. Returns
    None for a frame that isn't Modbus (protocol identifier != 0) or whose
    MBAP length disagrees with the bytes received -- per the spec a
    server silently discards those rather than guessing."""
    if len(frame) < MBAP_HEADER_LEN + 1:
        return None
    transaction, protocol, length, unit = struct.unpack(">HHHB", frame[:MBAP_HEADER_LEN])
    if protocol != 0 or length != len(frame) - 6:
        return None
    response = handle_pdu(store, frame[MBAP_HEADER_LEN:])
    return struct.pack(">HHHB", transaction, 0, len(response) + 1, unit) + response


# ---- the TCP server ----------------------------------------------------------

def _recv_exact(sock, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class _Handler(socketserver.BaseRequestHandler):
    server: "ModbusServer"

    def handle(self) -> None:
        # One connection may carry many requests; a client typically keeps
        # it open for its whole session.
        while True:
            header = _recv_exact(self.request, MBAP_HEADER_LEN)
            if header is None:
                return
            length = struct.unpack(">H", header[4:6])[0]
            if not 2 <= length <= MAX_ADU_LEN - 6:
                return  # not a sane Modbus frame; drop the connection
            rest = _recv_exact(self.request, length - 1)
            if rest is None:
                return
            with self.server.lock:
                self.server.peer = self.client_address  # who this request is from, for the store's callbacks
                response = handle_adu(self.server.store, header + rest)
            if response is not None:
                self.request.sendall(response)


class ModbusServer(socketserver.ThreadingTCPServer):
    """Serves `store` on (host, port). Every request is handled while
    holding `lock` -- pass the lock that also guards whatever else
    mutates the store, so a Modbus read is always a consistent snapshot.
    Port 0 picks a free port (see `.server_address`). 502 is the
    registered Modbus port but is privileged on most systems; 5020 is the
    common unprivileged convention."""

    daemon_threads = True
    # POSIX: SO_REUSEADDR only lets a restarted server rebind past TIME_WAIT.
    # Windows: it lets a second server bind a port already being served, and
    # clients then land on either one -- two plants silently sharing 5020.
    # So not there: a second server on a busy port fails loudly instead.
    allow_reuse_address = os.name != "nt"

    def __init__(self, store: DataStore, host: str = "127.0.0.1", port: int = 5020, lock: threading.Lock | None = None) -> None:
        self.store = store
        self.lock = lock or threading.Lock()
        self.peer: tuple | None = None  # the client whose request is being handled (under `lock`)
        super().__init__((host, port), _Handler)


# ---- the TCP client ----------------------------------------------------------


class ModbusClient:
    """A minimal blocking Modbus TCP client (Phase 7 step 3) -- the other
    half of the same protocol subset, so the reference external controller
    needs no runtime dependency either. One request at a time on one
    connection; each response's transaction ID must echo the request's.
    An exception response raises ModbusError with its code; a dropped or
    garbled connection raises ConnectionError.

    Its framing is checked against the server above, whose parsing is
    itself pinned to the spec's worked examples and to pymodbus's client
    (tests/unit/test_modbus.py, tests/integration/test_modbus_interop.py),
    so a client frame the server accepts is a spec-conformant frame."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5020, timeout: float = 2.0, unit: int = 1) -> None:
        import socket

        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.unit = unit
        self._transaction = 0

    def close(self) -> None:
        self._sock.close()

    def __enter__(self) -> "ModbusClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, pdu: bytes) -> bytes:
        self._transaction = (self._transaction + 1) & 0xFFFF
        self._sock.sendall(struct.pack(">HHHB", self._transaction, 0, len(pdu) + 1, self.unit) + pdu)
        header = _recv_exact(self._sock, MBAP_HEADER_LEN)
        if header is None:
            raise ConnectionError("server closed the connection")
        transaction, protocol, length, _unit = struct.unpack(">HHHB", header)
        body = _recv_exact(self._sock, length - 1) if length >= 2 else None
        if body is None or transaction != self._transaction or protocol != 0:
            raise ConnectionError("malformed or mismatched Modbus response")
        if body[0] & 0x80:
            raise ModbusError(body[1], f"function {pdu[0]:#04x} failed with exception {body[1]:#04x}")
        if body[0] != pdu[0]:
            raise ConnectionError(f"response to function {body[0]:#04x}, expected {pdu[0]:#04x}")
        return body

    def _read_bits(self, function: int, address: int, count: int) -> list[bool]:
        body = self._request(struct.pack(">BHH", function, address, count))
        return unpack_bits(body[2 : 2 + body[1]], count)

    def _read_registers(self, function: int, address: int, count: int) -> list[int]:
        body = self._request(struct.pack(">BHH", function, address, count))
        return list(struct.unpack(f">{count}H", body[2 : 2 + 2 * count]))

    def read_coils(self, address: int, count: int) -> list[bool]:
        return self._read_bits(0x01, address, count)

    def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        return self._read_bits(0x02, address, count)

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        return self._read_registers(0x03, address, count)

    def read_input_registers(self, address: int, count: int) -> list[int]:
        return self._read_registers(0x04, address, count)

    def write_coil(self, address: int, value: bool) -> None:
        self._request(struct.pack(">BHH", 0x05, address, 0xFF00 if value else 0x0000))

    def write_register(self, address: int, value: int) -> None:
        self._request(struct.pack(">BHH", 0x06, address, value))

    def write_coils(self, address: int, values: list[bool]) -> None:
        data = pack_bits(values)
        self._request(struct.pack(">BHHB", 0x0F, address, len(values), len(data)) + data)

    def write_registers(self, address: int, values: list[int]) -> None:
        self._request(struct.pack(f">BHHB{len(values)}H", 0x10, address, len(values), 2 * len(values), *values))
