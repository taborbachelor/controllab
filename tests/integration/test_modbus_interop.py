"""Our stdlib Modbus server, driven over a real localhost socket by
pymodbus's client -- an independent implementation. This is the
condition Phase 7 scoping set for hand-rolling the protocol: if framing,
bit order, or byte counts were wrong, a third-party client would
disagree. pymodbus is a dev-only dependency; ControlLab's runtime never
imports it."""
import socket
import struct
import threading

import pytest

pymodbus_client = pytest.importorskip("pymodbus.client")

from services.protocols.modbus import MemoryDataStore, ModbusServer  # noqa: E402


@pytest.fixture
def served():
    store = MemoryDataStore(coils=64, discrete_inputs=64, holding_registers=64, input_registers=64)
    server = ModbusServer(store, port=0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    host, port = server.server_address
    client = pymodbus_client.ModbusTcpClient(host, port=port, timeout=2, retries=0)
    assert client.connect()
    yield store, client, (host, port)
    client.close()
    server.shutdown()
    server.server_close()


def test_bits_both_directions(served):
    store, client, _ = served
    pattern = [i % 3 == 0 for i in range(20)]
    assert not client.write_coils(5, pattern).isError()
    assert store.coils[5:25] == pattern
    assert client.read_coils(5, count=20).bits[:20] == pattern
    assert not client.write_coil(63, True).isError()
    assert store.coils[63] is True

    store.discrete_inputs[10:13] = [True, False, True]
    assert client.read_discrete_inputs(10, count=3).bits[:3] == [True, False, True]


def test_registers_both_directions(served):
    store, client, _ = served
    assert not client.write_registers(2, [1, 65535, 0x1234]).isError()
    assert store.holding_registers[2:5] == [1, 65535, 0x1234]
    assert client.read_holding_registers(2, count=3).registers == [1, 65535, 0x1234]
    assert not client.write_register(0, 42).isError()
    assert store.holding_registers[0] == 42

    store.input_registers[60:64] = [9, 8, 7, 6]
    assert client.read_input_registers(60, count=4).registers == [9, 8, 7, 6]


def test_exception_responses_are_understood_by_a_third_party_client(served):
    _, client, _ = served
    rr = client.read_holding_registers(63, count=2)  # runs off the end
    assert rr.isError()
    assert rr.exception_code == 0x02


def test_one_connection_carries_many_requests(served):
    _, client, _ = served
    for i in range(50):
        client.write_register(1, i)
        assert client.read_holding_registers(1, count=1).registers == [i]


def test_many_clients_at_once(served):
    store, _, (host, port) = served
    errors = []

    def worker(address):
        c = pymodbus_client.ModbusTcpClient(host, port=port, timeout=2, retries=0)
        try:
            c.connect()
            for v in range(20):
                c.write_register(address, v)
                if c.read_holding_registers(address, count=1).registers != [v]:
                    errors.append(address)
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(a,)) for a in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert errors == []
    assert store.holding_registers[:8] == [19] * 8


def test_insane_mbap_length_drops_the_connection(served):
    _, _, (host, port) = served
    with socket.create_connection((host, port), timeout=2) as s:
        s.sendall(struct.pack(">HHHB", 1, 0, 0xFFFF, 1))
        assert s.recv(16) == b""  # server closed it rather than waiting for 64 KB


def test_binds_localhost_by_default():
    server = ModbusServer(MemoryDataStore(), port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
