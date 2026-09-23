"""The real line over Modbus, end to end: a LiveSession (the dashboard's
core) served through LINE_REGISTER_MAP, driven by pymodbus's client.
The session is stepped by hand -- no Pacer -- so this is deterministic."""
import threading

import pytest

pymodbus_client = pytest.importorskip("pymodbus.client")

from services.protocols.line_map import LINE_REGISTER_MAP  # noqa: E402
from services.protocols.modbus import ModbusServer  # noqa: E402
from services.protocols.register_map import IOImageDataStore  # noqa: E402
from services.visualization.live import LiveSession  # noqa: E402

START, STOP = 100, 101


@pytest.fixture
def line():
    session = LiveSession()
    store = IOImageDataStore(LINE_REGISTER_MAP, lambda: session.io, on_command=session.command)
    server = ModbusServer(store, port=0, lock=session.lock)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    client = pymodbus_client.ModbusTcpClient("127.0.0.1", port=server.server_address[1], timeout=2, retries=0)
    assert client.connect()
    yield session, client
    client.close()
    server.shutdown()
    server.server_close()


def steps(session, n):
    for _ in range(n):
        session.step()


def test_a_plc_reads_the_idle_line(line):
    session, client = line
    session.step()
    di = client.read_discrete_inputs(0, count=11).bits[:11]
    assert di[2] is True  # ZSC-102: gate closed
    assert di[10] is True  # ES-001: healthy (fail-safe polarity)
    assert client.read_input_registers(0, count=2).registers == [2000, 0]  # bin 20.00 %, hopper 0.0 kg


def test_an_hmi_coil_starts_the_line_and_the_outputs_follow(line):
    session, client = line
    assert not client.write_coil(START, True).isError()
    steps(session, 20)
    assert session.snapshot()["state"] == "running"
    assert client.read_coils(0, count=3).bits[:3] == [True, True, True]  # gate open, feeder run, conveyor run
    assert client.read_holding_registers(0, count=1).registers == [10000]  # SC-103 = 100.00 %
    assert client.read_input_registers(1, count=1).registers == [0]  # material still crossing the belt
    steps(session, 30)  # 4 m belt at 2 m/s: 2 s of transit before anything lands
    assert client.read_input_registers(1, count=1).registers[0] > 0  # hopper weight rising

    client.write_coil(STOP, True)
    steps(session, 40)
    assert session.snapshot()["state"] == "idle"


def test_a_plc_cannot_override_the_built_in_controller(line):
    session, client = line
    rr = client.write_coil(1, True)  # try to force the feeder on
    assert rr.isError() and rr.exception_code == 0x02
    session.step()
    assert client.read_coils(1, count=1).bits[0] is False


def test_modbus_commands_show_up_in_the_session_telemetry(line):
    session, client = line
    client.write_coil(START, True)
    session.step()
    assert ("command_issued", "start") in [(e["type"], e.get("command")) for e in session.snapshot()["events"]]


def test_the_server_follows_a_new_session(line):
    session, client = line
    client.write_coil(START, True)
    steps(session, 20)
    session.restart()
    session.step()
    assert client.read_coils(0, count=3).bits[:3] == [False, False, False]
