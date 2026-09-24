// Shared HMI rendering (Phase 6): the line mimic plus the alarm, tag and
// event-text renderers. Included by replay_template.html and
// live_template.html via page.py, so both pages draw the line identically.
// Everything here is a pure function of the values passed in -- no page
// globals -- which is what lets a recorded frame and a live snapshot share it.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const TRIP = "var(--trip)", WARN = "var(--warn)", RUN = "var(--run)", OFF = "var(--hollow)", LINE = "var(--line)";

// Hopper geometry: fill spans y 310 (empty) .. 110 (full), a 200px column.
const HOP_TOP = 110, HOP_H = 200, BIN_TOP = 40, BIN_H = 130;
let PLANT = null;

function initMimic(plant) {
  PLANT = plant;
  const setpointY = (pct) => HOP_TOP + HOP_H * (1 - pct / 100);
  for (const [id, mark, pct] of [["lsh105", "lsh-mark", plant.hopper_high_pct], ["lshh105", "lshh-mark", plant.hopper_high_high_pct]]) {
    const y = setpointY(pct);
    $(mark).setAttribute("y1", y); $(mark).setAttribute("y2", y);
    $(id).setAttribute("transform", `translate(0 ${y})`);
  }
}

function lamp(groupId, on, color) {
  $(groupId).querySelector("circle").setAttribute("fill", on ? color : OFF);
}

// A device's shape: dark when feedback says running, hollow when stopped,
// dashed amber when the command and the feedback disagree, red on a trip.
function device(el, cmd, fb, trip) {
  el.setAttribute("fill", trip ? TRIP : fb ? RUN : OFF);
  el.setAttribute("stroke", trip ? TRIP : cmd !== fb ? WARN : LINE);
  el.setAttribute("stroke-dasharray", !trip && cmd !== fb ? "6 4" : "none");
}

// `animate`: whether belts show moving material (only while time is advancing).
function renderMimic(v, animate) {
  let anyGateOpen = false;  // the feeder moves material only through an open gate
  // The three bins and their gates. A recording made before bins B and C
  // existed has no tags for them: those bins are hidden rather than drawn empty.
  for (const [grp, fill, lt, lsl, gateId, gateTxt, tLt, tLsl, tOpen, tClosed, tCmd] of [
    ["bin-a", "bin-fill", "lt101", "lsl101", "xv102", "xv102-txt", "LT-101", "LSL-101", "ZSO-102", "ZSC-102", "XV-102.CMD_OPEN"],
    ["bin-b", "bin-b-fill", "lt111", "lsl111", "xv112", "xv112-txt", "LT-111", "LSL-111", "ZSO-112", "ZSC-112", "XV-112.CMD_OPEN"],
    ["bin-c", "bin-c-fill", "lt121", "lsl121", "xv122", "xv122-txt", "LT-121", "LSL-121", "ZSO-122", "ZSC-122", "XV-122.CMD_OPEN"],
  ]) {
    const present = v[tLt] !== undefined;
    $(grp).style.display = present ? "" : "none";
    if (!present) continue;
    const binPct = Math.max(0, Math.min(100, v[tLt]));
    $(fill).setAttribute("y", BIN_TOP + BIN_H * (1 - binPct / 100));
    $(fill).setAttribute("height", BIN_H * binPct / 100);
    $(lt).textContent = `${binPct.toFixed(1)} %`;
    lamp(lsl, v[tLsl], WARN);
    const gateOpen = v[tOpen], gateClosed = v[tClosed], gateCmd = v[tCmd];
    const gateFb = gateOpen ? true : gateClosed ? false : null;  // null = travelling
    anyGateOpen = anyGateOpen || !!gateOpen;
    const gate = $(gateId);
    gate.setAttribute("fill", gateOpen ? RUN : OFF);
    gate.setAttribute("stroke", gateFb === gateCmd ? LINE : WARN);
    gate.setAttribute("stroke-dasharray", gateFb === gateCmd ? "none" : "6 4");
    $(gateTxt).textContent = (gateOpen ? "Open" : gateClosed ? "Closed" : gateCmd ? "Opening…" : "Closing…") +
      (gateFb !== null && gateFb !== gateCmd ? ` (told to ${gateCmd ? "open" : "close"})` : "");
  }

  const fRun = v["M-103.RUNNING"], fCmd = v["M-103.RUN"], fTrip = v["M-103.FAULT"], plugged = v["LSH-103"];
  device($("m103"), fCmd, fRun, fTrip);
  $("m103-l").setAttribute("fill", fRun || fTrip ? "#fff" : "var(--ink)");
  // LSH-103, the discharge-chute plug switch: a jam. The drive still reports
  // RUNNING through one, so this is the only sign of it on the mimic.
  $("feeder-body").setAttribute("stroke", fTrip || plugged ? TRIP : LINE);
  $("m103-txt").textContent = (fTrip ? "Drive fault" : plugged ? "Jammed (chute plug switch LSH-103)" : fRun ? `Running at ${v["SC-103"].toFixed(0)} % speed` : "Stopped") +
    (!fTrip && fCmd !== fRun ? ` (told to ${fCmd ? "run" : "stop"})` : "");

  const cRun = v["M-104.RUNNING"], cCmd = v["M-104.RUN"], cTrip = v["M-104.OL"], motion = v["ZSS-104"];
  device($("m104"), cCmd, cRun, cTrip);
  $("m104-l").setAttribute("fill", cRun || cTrip ? "#fff" : "var(--ink)");
  $("conv-belt").setAttribute("stroke", cTrip ? TRIP : cRun && !motion ? WARN : LINE);
  $("m104-txt").textContent = (cTrip ? "Overload trip" : cRun && !motion ? "Motor on, belt not moving" : cRun ? "Running" : "Stopped") +
    (!cTrip && cCmd !== cRun ? ` (told to ${cCmd ? "run" : "stop"})` : "");
  // The motor current (IT-104) and the belt scale (FT-104): a jam shows as a
  // current far over the motor's rating with nothing on the scale.
  $("m104-io").textContent = v["IT-104"] !== undefined
    ? `motor ${v["IT-104"].toFixed(1)} A · belt scale ${v["FT-104"].toFixed(1)} kg/s` : "";
  lamp("zss104", motion, RUN);

  // Material only visibly moves where it physically can.
  const feeding = fRun && anyGateOpen;
  for (const [id, on] of [["feeder-flow", feeding], ["conv-flow", motion]]) {
    $(id).setAttribute("opacity", on ? 1 : 0);
    $(id).classList.toggle("flowing", on && animate);
  }

  const kg = v["WT-105"], hopPct = Math.max(0, Math.min(100, 100 * kg / PLANT.hopper_capacity_kg));
  $("hop-fill").setAttribute("y", HOP_TOP + HOP_H * (1 - hopPct / 100));
  $("hop-fill").setAttribute("height", HOP_H * hopPct / 100);
  // A failed transmitter reads 0 kg, the same as an empty hopper; only its
  // channel fault (WT-105.FLT) says the number is meaningless.
  $("wt105").textContent = v["WT-105.FLT"] ? "Weight signal FAILED" : `${kg.toFixed(0)} kg · ${hopPct.toFixed(1)} % full`;
  // Fail-safe switches: 1 = below the switch point, so the lamp lights on 0.
  lamp("lsh105", !v["LSH-105"], WARN);
  lamp("lshh105", !v["LSHH-105"], TRIP);

  const healthy = v["ES-001"];
  $("es001").setAttribute("fill", healthy ? OFF : TRIP);
  $("es001").setAttribute("stroke", healthy ? LINE : TRIP);
  $("es001-l").setAttribute("fill", healthy ? "var(--ink)" : "#fff");
}

function renderState(state) {
  $("state").textContent = state.toUpperCase();
  $("state").className = "state " + state;
}

function fmt(v) { return typeof v === "boolean" ? (v ? "1" : "0") : v.toFixed(2); }

// `prev`: the previous tick's values, for changed-this-tick highlighting.
function renderTags(tags, v, prev) {
  $("tags").innerHTML = tags.map((t) =>
    `<tr class="${prev && v[t.name] !== prev[t.name] ? "changed" : ""}" title="${esc(t.description)}">` +
    `<td>${esc(t.name)}</td><td>${t.type}</td><td class="num">${fmt(v[t.name])}${t.units ? " " + esc(t.units) : ""}</td></tr>`).join("");
}

function renderAlarms(alarms) {
  if (!alarms.length) { $("alarms").innerHTML = '<p class="empty">No latched alarms.</p>'; return; }
  $("alarms").innerHTML = "<table><thead><tr><th>Alarm</th><th>Status</th></tr></thead><tbody>" + alarms.map((x) =>
    `<tr class="${x.is_warning ? "alarm-warn" : "alarm-trip"} ${x.active ? "" : "alarm-cleared"}">` +
    `<td><strong>${esc(x.id)}</strong>${x.first_out ? '<span class="fo">FIRST OUT</span>' : ""}<br>${esc(x.description)}</td>` +
    `<td>${x.active ? "ACTIVE" : "cleared"} · ${x.acknowledged ? "acked" : "unacked"}</td></tr>`).join("") + "</tbody></table>";
}

function describe(e) {
  switch (e.type) {
    case "command_issued": return `Command: <strong>${esc(e.command)}</strong>`;
    case "state_changed": return `State ${esc(e.from)} → <strong>${esc(e.to)}</strong>` +
      (e.fault_reason && (e.to === "faulted" || e.to === "estopped") ? ` (${esc(e.fault_reason)})` : "");
    case "alarm_activated": return `${e.is_warning ? "Warning" : "Alarm"} <strong>${esc(e.alarm_id)}</strong> active${e.first_out ? " · first out" : ""}`;
    case "alarm_cleared": return `Alarm ${esc(e.alarm_id)} cleared`;
    case "alarm_acknowledged": return `Alarm ${esc(e.alarm_id)} acknowledged`;
    case "controller_watchdog": return `<strong>Controller watchdog</strong>: no output write for ${e.timeout_s} s, outputs forced off`;
    default: return esc(e.type);
  }
}

// ---- The test panel: a scenario's setup and stages, each with its actions,
// what it expects and its time limit, marked as a run reaches it. Shared by
// the replay (driven by the recorded summary, frame by frame) and the live
// dashboard (driven by the runner's progress, then the summary). Pure view:
// every status and time it shows is handed to it.
const TP_MARK = { pending: "○", running: "▶", passed: "✓", failed: "✗", not_run: "–", not_observable: "?", done: "✓" };
const TP_CHECK = { match: "MATCH", mismatch: "MISMATCH", not_reached: "not reached", not_run: "not run", not_observed: "not observed" };
function tpVal(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "none";
  return String(v);
}

// `plan`: {setup_text, stages: [{n, title, within_s, actions: [{kind, text}], checks: [{label, expected}]}]}
// (verdict.plan(), or a run summary, which has the same shape plus outcomes).
function buildTestPanel(el, plan) {
  el.innerHTML = `<li data-st="0"><p class="tst-h"><span class="tst-mk"></span><span>Setup: bring the line to the starting condition</span></p>` +
    `<p class="tst-do">${plan.setup_text.map((x) => `<span>${esc(x)}</span>`).join("")}</p></li>` +
    plan.stages.map((st) =>
      `<li data-st="${st.n}"><p class="tst-h"><span class="tst-mk"></span><span>Stage ${st.n}: ${esc(st.title || "")}</span></p>` +
      `<p class="tst-time"></p>` +
      `<p class="tst-do">${st.actions.length ? st.actions.map((a) => `<span class="${a.kind}">${esc(a.text)}</span>`).join("")
                                              : "<span>No action: keep watching</span>"}</p>` +
      `<table class="tst-x"><tbody>${st.checks.map((c, j) =>
        `<tr data-j="${j}"><td class="mk">expect</td><td>${esc(c.label)}</td><td class="v">${esc(tpVal(c.expected))}</td></tr>`).join("")}` +
      "</tbody></table></li>").join("");
}

// status: running | done | failed | pending
function setTestSetup(el, status) {
  const li = el.querySelector('[data-st="0"]');
  li.className = status === "done" ? "passed" : status;
  li.querySelector(".tst-mk").textContent = TP_MARK[status];
}

// status: pending | running | passed | failed | not_run | not_observable.
// o.elapsed (running), o.response (passed), o.deadline (failed: at its time
// limit, not an invariant stop), o.checks (the summary's checks, once known).
function setTestStage(el, st, status, o = {}) {
  const li = el.querySelector(`[data-st="${st.n}"]`);
  li.className = status;
  li.querySelector(".tst-mk").textContent = TP_MARK[status];
  li.querySelector(".tst-time").textContent =
    status === "running" ? `${(o.elapsed || 0).toFixed(1)} s elapsed · limit ${st.within_s} s` :
    status === "passed" ? (o.response != null ? `passed in ${o.response.toFixed(2)} s · limit ${st.within_s} s` : "passed") :
    status === "failed" ? (o.deadline ? `FAILED at its ${st.within_s} s deadline` : "FAILED: run stopped") :
    status === "not_run" ? "not run (the test stops at the first failure)" :
    status === "not_observable" ? "not observable without the controller's status block" : `limit ${st.within_s} s`;
  li.querySelectorAll("tr").forEach((tr) => {
    const c = o.checks ? o.checks[+tr.dataset.j] : null, spec = st.checks[+tr.dataset.j];
    const shown = c && status !== "running" && status !== "pending" ? c.status : status === "passed" ? "match" : null;
    tr.className = shown || "";
    tr.querySelector(".mk").textContent = shown ? TP_CHECK[shown] : "expect";
    tr.querySelector(".v").textContent = shown === "mismatch"
      ? `${tpVal(spec.expected)}, but got ${c.actual == null ? "none" : tpVal(c.actual)}` : tpVal(spec.expected);
  });
}
