"""`controllab test` on an engineer's own scenario files: a scenario outside
the repository's suite runs from its path (a file or a directory), and a
malformed one is reported in a sentence, never as a traceback."""
from __future__ import annotations

import textwrap

import pytest

from services.cli import main, select

ESTOP = textwrap.dedent("""
    name: My E-stop check
    given: {line_state: running}
    when: {estop: tripped}
    expect: {line_state: estopped, conveyor_run_commanded: false}
    within: {seconds: 0.5}
""")


def test_a_scenario_file_outside_the_suite_runs_from_its_path(tmp_path, capsys):
    f = tmp_path / "estop.yaml"
    f.write_text(ESTOP)
    assert main(["test", str(f)]) == 0
    out = capsys.readouterr().out
    assert "1/1 scenarios passed; 2/2 checks matched." in out
    assert "My E-stop check" in out


def test_a_directory_runs_every_scenario_under_it_and_only_those(tmp_path):
    (tmp_path / "a.yaml").write_text(ESTOP)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.yaml").write_text(ESTOP.replace("My E-stop check", "Another"))
    assert [s.name for s in select([str(tmp_path)])] == ["My E-stop check", "Another"]


def test_paths_and_suite_name_fragments_combine(tmp_path):
    f = tmp_path / "estop.yaml"
    f.write_text(ESTOP)
    names = [s.name for s in select([str(f), "feeder_jam_recovery"])]
    assert names[0] == "My E-stop check" and len(names) == 2


def test_a_failing_scenario_of_your_own_exits_nonzero(tmp_path, capsys):
    f = tmp_path / "wrong.yaml"
    f.write_text(ESTOP.replace("line_state: estopped", "line_state: idle"))
    assert main(["test", str(f)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_an_unknown_key_is_reported_in_a_sentence(tmp_path):
    f = tmp_path / "typo.yaml"
    f.write_text(ESTOP.replace("estop: tripped", "estop_pressed: tripped"))
    with pytest.raises(SystemExit) as e:
        main(["test", str(f)])
    assert str(e.value).startswith("scenario error:") and "unknown given/when field: 'estop_pressed'" in str(e.value)


def test_a_file_missing_a_required_key_is_reported_in_a_sentence(tmp_path):
    f = tmp_path / "broken.yaml"
    f.write_text("name: no expect\nwithin: {seconds: 1}\n")
    with pytest.raises(SystemExit) as e:
        main(["test", str(f)])
    assert "cannot load scenario" in str(e.value) and "expect" in str(e.value)


def test_an_empty_directory_is_an_error_not_an_empty_pass(tmp_path):
    with pytest.raises(SystemExit) as e:
        main(["test", str(tmp_path)])
    assert "no scenario files" in str(e.value)
