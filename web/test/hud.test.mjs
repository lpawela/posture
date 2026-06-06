// Unit tests for the pure HUD logic (web/hud.js) — the set/rep label, tint
// mapping, rep-feedback latch, and navigate-away decision. These are the
// fiddly, repeatedly-regressed bits; testing them here (no DOM) pins them down.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  setInfoText,
  smoothDeviation,
  tintStyle,
  decideFeedback,
  navActionFor,
} from "../hud.js";

test("setInfoText: current set is 1-based and clamped; finished reads 'complete'", () => {
  const M = (completed_sets, current_set_reps, ts = 3, tr = 12) => ({
    completed_sets, current_set_reps, target_sets: ts, target_reps: tr,
  });
  assert.equal(setInfoText(M(0, 0)), "Set 1 / 3 · rep 0/12");
  assert.equal(setInfoText(M(0, 5)), "Set 1 / 3 · rep 5/12");
  assert.equal(setInfoText(M(1, 0)), "Set 2 / 3 · rep 0/12");
  assert.equal(setInfoText(M(2, 11)), "Set 3 / 3 · rep 11/12");
  assert.equal(setInfoText(M(3, 0)), "Set 3 / 3 · complete"); // no "Set 4 / 3"
  assert.equal(setInfoText(M(5, 0)), "Set 3 / 3 · complete"); // overshoot still clamps
});

test("setInfoText: free-form session (no target) shows em dashes, never 'complete'", () => {
  assert.equal(
    setInfoText({ completed_sets: 0, current_set_reps: 0, target_sets: null, target_reps: null }),
    "Set 1 / — · rep 0/—",
  );
  assert.equal(
    setInfoText({ completed_sets: 2, current_set_reps: 3, target_sets: null, target_reps: null }),
    "Set 3 / — · rep 3/—",
  );
});

test("smoothDeviation: EMA toward the raw value, snapping tiny residuals to 0", () => {
  assert.equal(smoothDeviation(0, 1), 0.5);
  assert.equal(smoothDeviation(0.5, 1), 0.75);
  assert.equal(smoothDeviation(0, 0), 0);
  // decays toward 0 and snaps once below 0.01 (so an in-bounds pose fully clears)
  let v = 0.5;
  for (let i = 0; i < 10; i++) v = smoothDeviation(v, 0);
  assert.equal(v, 0);
});

test("tintStyle: clear in-bounds, faint floor just out, ramps and clamps to red", () => {
  assert.equal(tintStyle(0).opacity, "0");
  assert.equal(tintStyle(0).backgroundColor, "hsl(60, 100%, 50%)"); // yellow at 0
  assert.equal(tintStyle(1).opacity, "0.500");
  assert.equal(tintStyle(1).backgroundColor, "hsl(0, 100%, 50%)"); // red at 1
  assert.equal(tintStyle(0.5).opacity, "0.290"); // 0.08 + 0.42*0.5
  assert.equal(tintStyle(2).opacity, "0.500"); // clamped
  assert.ok(parseFloat(tintStyle(0.05).opacity) > 0); // no dead-band: any drift shows
});

test("decideFeedback: a completed rep latches its result + faults for the hold window", () => {
  const d = decideFeedback(
    { rep_score: 80, feedback: "Squat deeper", state: "up", rep_count: 1 },
    1000, 0,
  );
  assert.equal(d.feedback, "Squat deeper");
  assert.equal(d.rebuildIssues, true);
  assert.equal(d.latched, true);
  assert.equal(d.holdUntil, 4000); // now + 3000
});

test("decideFeedback: descending into the next rep releases the hold and clears faults", () => {
  const d = decideFeedback(
    { rep_score: null, feedback: "Sit back and down", state: "down", rep_count: 1 },
    1000, 4000, // still within the hold...
  );
  assert.equal(d.feedback, "Sit back and down"); // ...but released because we're descending
  assert.equal(d.clearIssues, true);
  assert.equal(d.rebuildIssues, false);
});

test("decideFeedback: within the hold while standing, leave the line untouched", () => {
  const d = decideFeedback(
    { rep_score: null, feedback: "Stand tall", state: "up", rep_count: 1 },
    2000, 4000,
  );
  assert.equal(d.feedback, null); // hold not elapsed → keep the latched message
  assert.equal(d.clearIssues, false);
});

test("decideFeedback: after the hold elapses, show the live cue and clear faults", () => {
  const d = decideFeedback(
    { rep_score: null, feedback: "Stand tall", state: "up", rep_count: 1 },
    5000, 4000,
  );
  assert.equal(d.feedback, "Stand tall");
  assert.equal(d.clearIssues, true);
});

test("decideFeedback: before the first rep, never overwrite the setup hint", () => {
  const d = decideFeedback(
    { rep_score: null, feedback: "Stand tall", state: "up", rep_count: 0 },
    9999, 0,
  );
  assert.equal(d.feedback, null); // rep_count 0 → leave the setup hint in place
});

test("navActionFor: finish only when recording + has reps + socket open", () => {
  assert.equal(navActionFor({ recording: true, reps: 3, open: true }), "finish");
  assert.equal(navActionFor({ recording: true, reps: 0, open: true }), "stop");
  assert.equal(navActionFor({ recording: false, reps: 3, open: true }), "stop");
  assert.equal(navActionFor({ recording: true, reps: 3, open: false }), "stop");
});
