// Shared HMI rendering (Phase 6): the line mimic plus the alarm, tag and
// event-text renderers. Included by replay_template.html and
// live_template.html via page.py, so both pages draw the line identically.
// Everything here is a pure function of the values passed in -- no page
// globals -- which is what lets a recorded frame and a live snapshot share it.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const TRIP = "var(--trip)", WARN = "var(--warn)", RUN = "var(--run)", OFF = "var(--hollow)", LINE = "var(--line)";

// Hopper geometry: fill spans y 310 (empty) .. 110 (full), a 200px column.
const HOP_TOP = 110, HOP_H = 200, BIN_TOP = 30, BIN_H = 160;
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
  const binPct = Math.max(0, Math.min(100, v["LT-101"]));
  $("bin-fill").setAttribute("y", BIN_TOP + BIN_H * (1 - binPct / 100));
  $("bin-fill").setAttribute("height", BIN_H * binPct / 100);
  $("lt101").textContent = `LT-101  ${binPct.toFixed(1)} %`;
  lamp("lsl101", v["LSL-101"], WARN);

  const gateOpen = v["ZSO-102"], gateClosed = v["ZSC-102"], gateCmd = v["XV-102.CMD_OPEN"];
  const gateFb = gateOpen ? true : gateClosed ? false : null;  // null = travelling
  const gate = $("xv102");
  gate.setAttribute("fill", gateOpen ? RUN : OFF);
  gate.setAttribute("stroke", gateFb === gateCmd ? LINE : WARN);
  gate.setAttribute("stroke-dasharray", gateFb === gateCmd ? "none" : "6 4");
  $("xv102-txt").textContent = (gateOpen ? "OPEN" : gateClosed ? "CLOSED" : "TRAVELLING") + ` · cmd ${gateCmd ? "open" : "close"}`;

  const fRun = v["M-103.RUNNING"], fCmd = v["M-103.RUN"], fTrip = v["M-103.FAULT"], plugged = v["LSH-103"];
  device($("m103"), fCmd, fRun, fTrip);
  $("m103-l").setAttribute("fill", fRun || fTrip ? "#fff" : "var(--ink)");
  // LSH-103, the discharge-chute plug switch: a jam. The drive still reports
  // RUNNING through one, so this is the only sign of it on the mimic.
  $("feeder-body").setAttribute("stroke", fTrip || plugged ? TRIP : LINE);
  $("m103-txt").textContent = (fTrip ? "FAULT" : plugged ? "PLUGGED (LSH-103)" : fRun ? "RUNNING" : "STOPPED") + ` · cmd ${fCmd ? "run" : "stop"} · SC-103 ${v["SC-103"].toFixed(0)} %`;

  const cRun = v["M-104.RUNNING"], cCmd = v["M-104.RUN"], cTrip = v["M-104.OL"], motion = v["ZSS-104"];
  device($("m104"), cCmd, cRun, cTrip);
  $("m104-l").setAttribute("fill", cRun || cTrip ? "#fff" : "var(--ink)");
  $("conv-belt").setAttribute("stroke", cTrip ? TRIP : cRun && !motion ? WARN : LINE);
  $("m104-txt").textContent = (cTrip ? "OVERLOAD" : cRun ? "RUNNING" : "STOPPED") + ` · cmd ${cCmd ? "run" : "stop"} · motion ${motion ? "yes" : "no"}`;
  lamp("zss104", motion, RUN);

  // Material only visibly moves where it physically can.
  const feeding = fRun && gateOpen;
  for (const [id, on] of [["feeder-flow", feeding], ["conv-flow", motion]]) {
    $(id).setAttribute("opacity", on ? 1 : 0);
    $(id).classList.toggle("flowing", on && animate);
  }

  const kg = v["WT-105"], hopPct = Math.max(0, Math.min(100, 100 * kg / PLANT.hopper_capacity_kg));
  $("hop-fill").setAttribute("y", HOP_TOP + HOP_H * (1 - hopPct / 100));
  $("hop-fill").setAttribute("height", HOP_H * hopPct / 100);
  // A failed transmitter reads 0 kg, the same as an empty hopper; only its
  // channel fault (WT-105.FLT) says the number is meaningless.
  $("wt105").textContent = v["WT-105.FLT"] ? "WT-105  FAILED (channel fault)" : `WT-105  ${kg.toFixed(0)} kg  (${hopPct.toFixed(1)} %)`;
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
