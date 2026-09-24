"""The OPC UA server (master specification, item 8), driven by asyncua's own
client over a real opc.tcp connection. Skipped unless the optional extra is
installed: pip install -e ".[opcua]"."""
import asyncio
import socket

import pytest

asyncua = pytest.importorskip("asyncua")

from asyncua import Client, ua  # noqa: E402

from services.protocols.opcua_server import NAMESPACE, LineOpcUaServer, method_name  # noqa: E402
from services.visualization.live import LiveSession  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def with_server(body, session=None):
    session = session or LiveSession()
    endpoint = f"opc.tcp://127.0.0.1:{free_port()}/controllab/"
    server = LineOpcUaServer(session, endpoint=endpoint, log=lambda _: None)
    await server.build()
    async with server.server:
        await server.update()
        async with Client(endpoint) as client:
            idx = await client.get_namespace_index(NAMESPACE)

            def node(path):
                return client.get_node(ua.NodeId(f"Line1.{path}", idx))
            await body(session, server, client, node)


def run(body, session=None):
    asyncio.run(with_server(body, session))


def test_every_tag_is_served_with_its_type_description_and_current_value():
    async def body(session, server, client, node):
        values = session.snapshot()["values"]
        for tag in session.config()["tags"]:
            n = node(f"Tags.{tag['name']}")
            value = await n.read_value()
            vtype = await n.read_data_type_as_variant_type()
            if tag["type"] in ("AI", "AO"):
                assert vtype == ua.VariantType.Double and value == pytest.approx(values[tag["name"]])
            else:
                assert vtype == ua.VariantType.Boolean and value == values[tag["name"]]
            assert (await n.read_description()).Text.startswith(tag["description"])
        # Browsable from the Objects folder by name, as a SCADA client finds it.
        idx = await client.get_namespace_index(NAMESPACE)
        line = await client.nodes.objects.get_child([f"{idx}:ControlLab", f"{idx}:Line1"])
        assert {(await c.read_browse_name()).Name for c in await line.get_children()} >= {
            "Tags", "Controller", "Setpoints"}
    run(body)


def test_a_method_call_starts_the_line_and_the_state_follows():
    async def body(session, server, client, node):
        idx = await client.get_namespace_index(NAMESPACE)
        controller = node("Controller")
        assert await node("Controller.State").read_value() == "idle"
        await controller.call_method(ua.NodeId(f"Line1.Controller.{method_name('start')}", idx))
        for _ in range(3):
            session.step()
        await server.update()
        assert await node("Controller.State").read_value() == "starting"
        assert await node("Tags.M-104.RUN").read_value() is True
    run(body)


def test_a_refused_start_is_readable_as_the_reason():
    async def body(session, server, client, node):
        idx = await client.get_namespace_index(NAMESPACE)
        await node("Controller").call_method(ua.NodeId(f"Line1.Controller.{method_name('select_batch')}", idx))
        session.step()
        await node("Controller").call_method(ua.NodeId("Line1.Controller.Start", idx))
        session.step()
        await server.update()
        assert await node("Controller.LineMode").read_value() == "batch"
        assert "recipe is empty" in await node("Controller.LastStartRefusal").read_value()
    run(body)


def test_a_setpoint_written_by_a_client_reaches_the_controller_and_a_bad_one_is_put_back():
    async def body(session, server, client, node):
        await node("Setpoints.RecipeBKg").write_value(ua.Variant(250.0, ua.VariantType.Double))
        await node("Setpoints.SourceBin").write_value(ua.Variant("C", ua.VariantType.String))
        await server.update()  # taken, applied at the next tick
        assert await node("Setpoints.RecipeBKg").read_value() == 250.0  # not undone while it waits
        session.step()
        await server.update()
        assert session.rig.line.recipe["B"] == 250.0 and session.rig.line.source_bin == "C"
        assert await node("Controller.SourceBin").read_value() == "C"
        await node("Setpoints.SourceBin").write_value(ua.Variant("D", ua.VariantType.String))
        await server.update()  # refused
        session.step()
        await server.update()  # the session's value written back
        assert await node("Setpoints.SourceBin").read_value() == "C"
    run(body)


def test_tags_are_read_only_to_clients():
    async def body(session, server, client, node):
        with pytest.raises(ua.UaStatusCodeError):
            await node("Tags.M-104.RUN").write_value(ua.Variant(True, ua.VariantType.Boolean))
    run(body)


def test_a_command_during_a_verification_is_refused_with_a_status():
    async def body(session, server, client, node):
        idx = await client.get_namespace_index(NAMESPACE)
        session.verifying = "some scenario"
        with pytest.raises(ua.UaStatusCodeError):
            await node("Controller").call_method(ua.NodeId("Line1.Controller.Start", idx))
        session.verifying = None
    run(body)
