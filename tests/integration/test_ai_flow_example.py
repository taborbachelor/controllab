"""examples/ai_assist/run_flow.py, the complete AI loop, run offline with
the scripted stand-in: no API key, no network, no SDK needed."""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("run_flow", REPO / "examples" / "ai_assist" / "run_flow.py")
run_flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_flow)


def scenario_files():
    return {p: p.read_bytes() for p in (REPO / "scenarios").rglob("*.yaml")}


def test_the_whole_loop_runs_and_changes_nothing_it_shouldnt(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    before = scenario_files()
    assert run_flow.main(["--approve", "feeder_jam_during_start", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "READY FOR REVIEW  feeder_jam_during_start_faults_the_line.yaml" in out
    assert "REJECTED          weight_failure_stops_the_motors.yaml" in out      # its trigger doesn't matter
    assert "NEEDS JUDGMENT    weight_failure_while_stopping_faults_the_line.yaml" in out
    assert "PASS  Feeder Jam During Start Faults The Line" in out                 # approved -> executed
    analysis = (tmp_path / "analyses" / "weight_failure_while_stopping_faults_the_line.md").read_text(encoding="utf-8")
    assert "canned response, hand-written" in analysis  # a stand-in answer can't pass for a model's
    assert "not conclusions" in analysis
    assert scenario_files() == before


def test_nothing_executes_without_an_engineer_approving_it(tmp_path, capsys):
    assert run_flow.main(["--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "No candidate approved" in out and "PASS  " not in out


@pytest.mark.parametrize("name", ["weight_failure_stops_the_motors", "weight_failure_while_stopping"])
def test_only_a_candidate_the_gate_passed_can_be_approved(tmp_path, capsys, name):
    assert run_flow.main(["--approve", name, "--out", str(tmp_path)]) == 2
    assert "only a READY FOR REVIEW candidate can be approved" in capsys.readouterr().err
