"""Enforces the single most important rule in the architecture
(docs/CONTROL-LAB.md §3.2, CLAUDE.md §5): Control may only ever reach
Simulation through the shared I/O image, never by importing a simulation
object directly.

A plain text scan, not an ast walk — cheap, and it catches
"from services.simulation.equipment import X" exactly as well as
"import services.simulation.equipment.motor" without needing to handle
every way Python spells an import.
"""
from pathlib import Path

CONTROL_DIR = Path(__file__).resolve().parents[2] / "services" / "control"


def test_control_modules_never_reference_simulation_equipment_directly():
    py_files = sorted(CONTROL_DIR.glob("*.py"))
    assert py_files, "expected services/control/*.py to exist"
    for path in py_files:
        text = path.read_text(encoding="utf-8")
        assert "simulation.equipment" not in text, (
            f"{path} references services.simulation.equipment — Control "
            "must only touch Simulation through the I/O image "
            "(docs/CONTROL-LAB.md §3.2)"
        )


def test_control_modules_never_import_telemetry():
    """Phase 5's architecture (docs/CONTROL-LAB.md §10): Telemetry observes
    Control from outside. The one Control-side hook -- LineController's
    command_sink -- is a plain callable precisely so Control never needs
    to know telemetry exists. An import here would invert that.

    Checks import lines only, unlike the simulation guard above: Control's
    docstrings legitimately explain the telemetry relationship in prose,
    and a bare substring match would flag that documentation."""
    for path in sorted(CONTROL_DIR.glob("*.py")):
        imports = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        assert not any("services.telemetry" in line for line in imports), (
            f"{path} references services.telemetry -- Control must not "
            "depend on the layer that observes it (docs/CONTROL-LAB.md §10, Phase 5)"
        )
