#!/usr/bin/env python
"""Starts the live dashboard (docs/CONTROL-LAB.md §10, Phase 6 step 3):
the simulated line running in real time, served on localhost.

    python scripts/dashboard.py              # http://127.0.0.1:8000
    python scripts/dashboard.py --port 8080 --speed 2
    python scripts/dashboard.py --modbus-port 5020   # also serve the I/O image over Modbus TCP
    python scripts/dashboard.py --external           # no built-in controller: an external one
                                                     # drives the plant over Modbus (default port 5020)
    python scripts/dashboard.py --mqtt 127.0.0.1:1883    # also publish telemetry to an MQTT broker
    python scripts/dashboard.py --opcua 4840             # also serve an OPC UA server (the [opcua] extra)

Localhost only, no authentication -- a local engineering tool, not a
network service. All the logic lives in services/visualization/live.py.
"""
from __future__ import annotations

import argparse
import threading
from http.server import ThreadingHTTPServer

from services.protocols import controller_status
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.modbus import ModbusServer
from services.protocols.register_map import IOImageDataStore
from services.visualization.live import SPEEDS, LiveSession, Pacer, make_handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--speed", type=float, default=1.0, choices=SPEEDS, help="simulated seconds per real second")
    parser.add_argument(
        "--modbus-port", type=int, default=None,
        help="also serve the I/O image over Modbus TCP on 127.0.0.1 (read-only outputs; HMI coils 100-103)",
    )
    parser.add_argument(
        "--external", action="store_true",
        help="run the plant with NO built-in controller; an external controller owns the outputs over Modbus "
        "(see scripts/external_controller.py). Implies --modbus-port 5020 unless one is given.",
    )
    parser.add_argument(
        "--mqtt", metavar="HOST[:PORT]", default=None,
        help="publish telemetry (tags, state, events) to this MQTT broker; see services/protocols/mqtt.py",
    )
    parser.add_argument("--mqtt-prefix", default="controllab/line1", help="MQTT topic prefix")
    parser.add_argument(
        "--opcua", metavar="PORT", type=int, default=None,
        help='also serve an OPC UA server on 127.0.0.1:PORT (needs pip install -e ".[opcua]")',
    )
    args = parser.parse_args()
    if args.external and args.modbus_port is None:
        args.modbus_port = 5020

    session = LiveSession(external=args.external)
    pacer = Pacer(session, speed=args.speed)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(session, pacer))
    modbus = None
    if args.modbus_port is not None:
        if args.external:
            # External-controller mode: the remote controller owns the outputs
            # and status, takes commands through the HMI request/ack words,
            # and every write it makes feeds the comm-loss watchdog. SCADA
            # pushbutton coils still work -- they become requests too.
            store = IOImageDataStore(
                LINE_REGISTER_MAP, lambda: session.io, on_command=session.command, outputs_writable=True,
                handshake=session.handshake, on_output_write=session.note_controller_write,
            )
        else:
            # Built-in controller mode: outputs stay read-only over Modbus (the
            # LineController owns them); HMI coils issue operator commands.
            store = IOImageDataStore(
                LINE_REGISTER_MAP, lambda: session.io, on_command=session.command,
                status_source=lambda: controller_status.encode(session.rig.line),
                on_setpoint=session.setpoint_raw, setpoint_source=session.setpoint_values,
            )
        modbus = ModbusServer(store, port=args.modbus_port, lock=session.lock)
        threading.Thread(target=modbus.serve_forever, daemon=True, name="controllab-modbus").start()
        print(f"Modbus TCP: 127.0.0.1:{modbus.server_address[1]}  (map: docs/MODBUS-MAP.md)")
    mqtt_halt = threading.Event()
    if args.mqtt is not None:
        from services.protocols import mqtt

        host, _, port = args.mqtt.partition(":")
        publisher = mqtt.TelemetryPublisher(
            mqtt.MqttClient(host, int(port or 1883), client_id="controllab-dashboard"),
            session.snapshot, prefix=args.mqtt_prefix,
        )
        threading.Thread(target=mqtt.run_publisher, args=(publisher, mqtt_halt),
                         kwargs={"log": lambda m: print(m, flush=True)}, daemon=True,
                         name="controllab-mqtt").start()
    opcua_halt = None
    if args.opcua is not None:
        from services.protocols import opcua_server

        _, opcua_halt = opcua_server.start_in_thread(
            opcua_server.LineOpcUaServer(session, endpoint=f"opc.tcp://127.0.0.1:{args.opcua}/controllab/"))
    pacer.start()
    print(f"ControlLab live dashboard: http://127.0.0.1:{server.server_port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        pacer.stop()
        mqtt_halt.set()
        if opcua_halt is not None:
            opcua_halt.set()
        server.server_close()
        if modbus is not None:
            modbus.shutdown()
            modbus.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
