"""The deliberate-regression fixtures (services/testing/regressions.py): each
is caught by the suite, and by its demonstration scenario at the stage it
should be; production passes everything; and the copied methods differ
from production only by the marked change."""
import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from services.cli import main
from services.control.line_controller import LineController
from services.testing.regressions import REGRESSIONS, JamTripRemoved, ResetIgnoresJam
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"
ALL = Scenario.discover(SCENARIOS)
FIRST_FAILING_STAGE = {"jam-trip-removed": 1, "reset-ignores-jam": 2, "high-high-switch-only": 1,
                       "feeder-starts-with-conveyor": 1, "purge-too-short": 4}


def test_production_passes_every_scenario():
    assert [s.name for s in ALL if not run_scenario(s).passed] == []


@pytest.mark.parametrize("name", REGRESSIONS)
def test_each_regression_is_caught_where_it_should_be(name):
    r = REGRESSIONS[name]
    assert any(not run_scenario(s, line_cls=r.cls).passed for s in ALL)
    result = run_scenario(Scenario.load(SCENARIOS / r.demo_scenario), line_cls=r.cls)
    assert not result.passed and result.failed_stage == FIRST_FAILING_STAGE[name]
    assert result.unmet  # a real expected-vs-actual, not only an error message


def _body(cls, method) -> str:
    """The method's statements, docstring and comments dropped, as code."""
    fn = ast.parse(textwrap.dedent(inspect.getsource(getattr(cls, method)))).body[0]
    body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) else fn.body
    return "\n".join(ast.unparse(stmt) for stmt in body)


def test_copied_methods_differ_from_production_only_by_the_marked_change():
    prod = _body(LineController, "_running_trip_reason")
    branch = "if self.interlocks.feeder_plugged:\n    return 'feeder jam'\n"
    assert prod.count(branch) == 1
    assert _body(JamTripRemoved, "_running_trip_reason") == prod.replace(branch, "")
    prod = _body(LineController, "_fault_cause_cleared")
    assert prod.count(" or self.interlocks.feeder_plugged") == 1
    assert _body(ResetIgnoresJam, "_fault_cause_cleared") == prod.replace(" or self.interlocks.feeder_plugged", "")


def test_cli_exits_nonzero_when_it_catches_a_regression_and_zero_when_clean(capsys):
    assert main(["test", "feeder_jam_recovery"]) == 0
    assert main(["test", "feeder_jam_recovery", "--regression", "jam-trip-removed"]) == 1
    out = capsys.readouterr().out
    assert "REGRESSION DETECTED" in out and "Failure detected at: stage 1" in out
    with pytest.raises(SystemExit):
        main(["test", "--regression", "no-such-thing"])
