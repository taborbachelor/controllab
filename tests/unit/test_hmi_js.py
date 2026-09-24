"""The shared line-picture script (services/visualization/hmi.js), run in
Node against a stub DOM: a script error there leaves the picture half-drawn
in every browser, and the Python suite can't see it. Found completing the
master specification (item 6): a variable moved into the per-bin loop was
still used after it, and the dashboard reported it only as "Lost connection".
Skipped where Node isn't installed."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.visualization.live import PLANT, LiveSession

HMI = Path(__file__).resolve().parents[2] / "services" / "visualization" / "hmi.js"
NODE = shutil.which("node")

STUB_DOM = """
const stub = () => {
  const el = { style: {}, textContent: "", innerHTML: "", dataset: {},
    setAttribute() {}, getAttribute() { return null; }, appendChild() {},
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } } };
  el.querySelector = () => stub();
  el.querySelectorAll = () => [];
  return el;
};
const elements = {};
globalThis.document = {
  getElementById: (id) => (elements[id] = elements[id] || stub()),
  querySelector: () => stub(),
  querySelectorAll: () => [],
};
"""


def run_js(values: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    script = tmp_path / "render.js"
    script.write_text(
        STUB_DOM + HMI.read_text(encoding="utf-8")
        + f"\ninitMimic({json.dumps(PLANT)});\nrenderMimic({json.dumps(values)}, true);\nconsole.log('rendered');\n",
        encoding="utf-8",
    )
    return subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_line_picture_renders_a_live_snapshot_without_a_script_error(tmp_path):
    s = LiveSession()
    s.command("start")
    for _ in range(30):
        s.step()
    result = run_js(s.snapshot()["values"], tmp_path)
    assert result.returncode == 0 and "rendered" in result.stdout, result.stderr


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_line_picture_renders_a_recording_made_before_bins_b_and_c(tmp_path):
    """Replays carry the tags of their day: the picture must cope without the
    bins B/C, motor-current and belt-scale tags."""
    values = LiveSession().snapshot()["values"]
    newer = ("LT-111", "LSL-111", "XV-112", "ZSO-112", "ZSC-112", "LT-121", "LSL-121", "XV-122", "ZSO-122", "ZSC-122",
             "IT-104", "FT-104")
    old = {k: v for k, v in values.items() if not k.startswith(newer)}
    result = run_js(old, tmp_path)
    assert result.returncode == 0 and "rendered" in result.stdout, result.stderr
