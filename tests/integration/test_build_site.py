"""The public demo (scripts/build_site.py) is real runs: each page's
embedded verdict is what the runner produced, the regression page fails
where the regression is caught, and a rebuild is byte-identical."""
import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load_script():
    spec = importlib.util.spec_from_file_location("build_site_script", REPO / "scripts" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def embedded(path: Path) -> dict:
    html = path.read_text(encoding="utf-8")
    return json.loads(re.search(r"const R = (.*?);\n", html).group(1).replace(r"<\/", "</"))


def test_the_demo_site_is_real_runs_and_rebuilds_identically(tmp_path):
    site = load_script()
    results = dict(site.build(tmp_path / "a"))
    assert results == {"index.html": True, "bad-change.html": False, "overfill.html": True, "normal.html": True,
                       "batch.html": True, "manual.html": True}
    bad = embedded(tmp_path / "a" / "bad-change.html")
    assert bad["summary"]["regression"] == "reset-ignores-jam"
    assert bad["summary"]["first_divergence"]["stage"] == 2
    index = embedded(tmp_path / "a" / "index.html")
    assert [n["href"] for n in index["meta"]["nav"]] == [f for f, *_ in site.RUNS]
    assert [n["current"] for n in index["meta"]["nav"]] == [True] + [False] * (len(site.RUNS) - 1)
    assert (tmp_path / "a" / ".nojekyll").exists()

    site.build(tmp_path / "b")
    for f, *_ in site.RUNS:
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f
