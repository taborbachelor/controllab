"""An OPC UA server for the live line (completing the master specification,
item 8).

OPC UA is far too large to hand-roll credibly (binary encoding, secure
channels, sessions, the address-space model), so this uses `asyncua`, as an
optional extra: `pip install -e ".[opcua]"`. Nothing else in ControlLab
imports it; without it, this module fails to import with a message saying
how to install it, and everything else runs as before.

What it serves (namespace `urn:controllab`, under Objects/ControlLab/Line1;
every node has a stable string NodeId, `ns=<urn:controllab>;s=Line1.Tags.WT-105`
and so on, so a client can address it directly without browsing):

    Tags/<TAG>          every I/O tag, read-only: Boolean for discrete, Double for
                        analog, with the tag's description and units
    Controller/         State, LineMode, FaultReason, LastStartRefusal, SourceBin,
                        ActiveBin, BatchLoadedKg, BatchesCompleted, ActiveAlarms,
                        UnacknowledgedAlarms, FirstOut (read-only)
    Controller/<Command>()   one method per HMI command (Start, Stop, Reset,
                        Acknowledge, SelectManual, ...), the same commands the
                        Modbus HMI registers carry
    Setpoints/          SourceBin ("A"/"B"/"C"), RecipeAKg, RecipeBKg, RecipeCKg,
                        HoldS: writable, validated like the dashboard's setpoints

It is an HMI/SCADA path onto the same session the dashboard runs, like the
Modbus server's HMI registers. It is not a controller path: the tags are
read-only, and an external controller still drives the plant over Modbus
(Phase 9). Values are published by exception every `interval_s`.

Security: like the Modbus server, a local engineering tool. It binds
127.0.0.1 with no security policy and anonymous access unless told
otherwise; exposing it on a network is the caller's explicit decision.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

try:
    from asyncua import Server, ua
except ImportError as exc:  # pragma: no cover -- exercised by hand, not in CI
    raise ImportError('the OPC UA server needs the optional extra: pip install -e ".[opcua]"') from exc

NAMESPACE = "urn:controllab"
SETPOINTS = {  # OPC UA name -> (dashboard setpoint, variant type)
    "SourceBin": ("source_bin", ua.VariantType.String),
    "RecipeAKg": ("recipe_a_kg", ua.VariantType.Double),
    "RecipeBKg": ("recipe_b_kg", ua.VariantType.Double),
    "RecipeCKg": ("recipe_c_kg", ua.VariantType.Double),
    "HoldS": ("hold_s", ua.VariantType.Double),
}
CONTROLLER = {  # OPC UA name -> (variant type, snapshot -> value)
    "State": (ua.VariantType.String, lambda s: s["state"]),
    "LineMode": (ua.VariantType.String, lambda s: s["line_mode"] or ""),
    "FaultReason": (ua.VariantType.String, lambda s: s["fault_reason"] or ""),
    "LastStartRefusal": (ua.VariantType.String, lambda s: "; ".join(s["last_start_refusal"])),
    "SourceBin": (ua.VariantType.String, lambda s: s["source_bin"]),
    "ActiveBin": (ua.VariantType.String, lambda s: s["active_bin"] or ""),
    "BatchLoadedKg": (ua.VariantType.Double, lambda s: float(s["batch"]["loaded_kg"]) if s["batch"] else 0.0),
    "BatchesCompleted": (ua.VariantType.Int32, lambda s: s["batch"]["completed"] if s["batch"] else 0),
    "ActiveAlarms": (ua.VariantType.String, lambda s: ", ".join(a["id"] for a in s["alarms"] if a["active"])),
    "UnacknowledgedAlarms": (ua.VariantType.String,
                             lambda s: ", ".join(a["id"] for a in s["alarms"] if not a["acknowledged"])),
    "FirstOut": (ua.VariantType.String, lambda s: next((a["id"] for a in s["alarms"] if a["first_out"]), "")),
}


def method_name(command: str) -> str:
    """`select_manual` -> `SelectManual`."""
    return "".join(part.capitalize() for part in command.split("_"))


def setpoint_values(snap: dict) -> dict[str, object]:
    """The setpoints as the session reports them (the external-controller
    mode has no recipe to report, so only the source bin)."""
    values: dict[str, object] = {"SourceBin": snap["source_bin"]}
    if snap["batch"]:
        recipe = snap["batch"]["recipe"]
        values |= {"RecipeAKg": float(recipe["A"]), "RecipeBKg": float(recipe["B"]),
                   "RecipeCKg": float(recipe["C"]), "HoldS": float(snap["batch"]["hold_s"])}
    return values


class LineOpcUaServer:
    """The address space above over a LiveSession-shaped `session`
    (snapshot(), config(), command(name), setpoint(name, value))."""

    def __init__(self, session, endpoint: str = "opc.tcp://127.0.0.1:4840/controllab/", interval_s: float = 0.1,
                 log: Callable[[str], None] = print) -> None:
        self.session = session
        self.endpoint = endpoint
        self.interval_s = interval_s
        self.log = log
        self.server = Server()
        self._tags: dict[str, object] = {}
        self._controller: dict[str, object] = {}
        self._setpoints: dict[str, object] = {}
        self._shown: dict[object, object] = {}  # node -> the value this server last wrote to it
        self._types: dict[object, object] = {}  # node -> its variant type (a write must match it exactly)
        self._reported: dict[str, object] = {}  # setpoint -> the value the session last reported
        self._since = 0

    async def build(self) -> None:
        await self.server.init()
        self.server.set_endpoint(self.endpoint)
        self.server.set_server_name("ControlLab")
        self.server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        idx = await self.server.register_namespace(NAMESPACE)
        root = await self.server.nodes.objects.add_object(ua.NodeId("ControlLab", idx), ua.QualifiedName("ControlLab", idx))
        line = await root.add_object(ua.NodeId("Line1", idx), ua.QualifiedName("Line1", idx))
        config = self.session.config()

        tags = await line.add_folder(ua.NodeId("Line1.Tags", idx), ua.QualifiedName("Tags", idx))
        for tag in config["tags"]:
            analog = tag["type"] in ("AI", "AO")
            node = await tags.add_variable(
                ua.NodeId(f"Line1.Tags.{tag['name']}", idx), ua.QualifiedName(tag["name"], idx),
                ua.Variant(0.0 if analog else False, ua.VariantType.Double if analog else ua.VariantType.Boolean),
            )
            self._types[node] = ua.VariantType.Double if analog else ua.VariantType.Boolean
            text = tag["description"] + (f" ({tag['units']})" if tag.get("units") else "")
            await node.write_attribute(ua.AttributeIds.Description, ua.DataValue(ua.LocalizedText(text)))
            self._tags[tag["name"]] = node

        controller = await line.add_object(ua.NodeId("Line1.Controller", idx), ua.QualifiedName("Controller", idx))
        for name, (vtype, _) in CONTROLLER.items():
            self._controller[name] = await controller.add_variable(
                ua.NodeId(f"Line1.Controller.{name}", idx), ua.QualifiedName(name, idx), ua.Variant(_empty(vtype), vtype))
            self._types[self._controller[name]] = vtype
        for command in config["commands"]:
            await controller.add_method(
                ua.NodeId(f"Line1.Controller.{method_name(command)}", idx), ua.QualifiedName(method_name(command), idx),
                self._method(command), [], [])

        setpoints = await line.add_folder(ua.NodeId("Line1.Setpoints", idx), ua.QualifiedName("Setpoints", idx))
        for name, (_, vtype) in SETPOINTS.items():
            node = await setpoints.add_variable(ua.NodeId(f"Line1.Setpoints.{name}", idx), ua.QualifiedName(name, idx),
                                                ua.Variant(_empty(vtype), vtype))
            await node.set_writable()
            self._types[node] = vtype
            self._setpoints[name] = node

    def _method(self, command: str):
        def call(parent):
            try:
                self.session.command(command)
            except ValueError as exc:  # a verification owns the line
                raise ua.UaStatusCodeError(ua.StatusCodes.BadInvalidState) from exc
            return []
        return call

    async def update(self) -> None:
        """One publish cycle: take any setpoint a client wrote, then write
        what changed in the session."""
        snap = self.session.snapshot(self._since)  # values and state; the events aren't served
        self._since = snap["event_count"]
        for name, node in self._setpoints.items():
            value = await node.read_value()
            if node in self._shown and value != self._shown[node]:
                self._take_setpoint(name, value)
                self._shown[node] = value
        for name, value in snap["values"].items():
            node = self._tags.get(name)
            if node is not None:
                await self._show(node, value)
        for name, (_, get) in CONTROLLER.items():
            await self._show(self._controller[name], get(snap))
        for name, value in setpoint_values(snap).items():
            # Written only when the session's value changes, so a client's write
            # isn't undone while it waits for the next tick to apply it.
            if self._reported.get(name) != value:
                self._reported[name] = value
                await self._show(self._setpoints[name], value)

    def _take_setpoint(self, name: str, value: object) -> None:
        setpoint = SETPOINTS[name][0]
        try:
            self.session.setpoint(setpoint, value)
        except ValueError as exc:
            self.log(f"OPC UA: setpoint {name} = {value!r} refused: {exc}")
            self._reported.pop(name, None)  # the next cycle writes the session's value back

    async def _show(self, node, value) -> None:
        vtype = self._types[node]
        if vtype == ua.VariantType.Double:
            value = float(value)
        if self._shown.get(node) != value:
            await node.write_value(ua.Variant(value, vtype))
            self._shown[node] = value

    async def serve(self, halt: threading.Event) -> None:
        await self.build()
        async with self.server:
            self.log(f"OPC UA: {self.endpoint}")
            while not halt.is_set():
                await self.update()
                await asyncio.sleep(self.interval_s)


def _empty(vtype):
    return {ua.VariantType.String: "", ua.VariantType.Double: 0.0, ua.VariantType.Int32: 0}[vtype]


def start_in_thread(server: LineOpcUaServer) -> tuple[threading.Thread, threading.Event]:
    """Run the server on its own event loop in a daemon thread; set the
    returned event to stop it."""
    halt = threading.Event()
    thread = threading.Thread(target=lambda: asyncio.run(server.serve(halt)), daemon=True, name="controllab-opcua")
    thread.start()
    return thread, halt
