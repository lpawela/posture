// jsdom integration: drives app.js's DOM glue (renderAnalysis / showPage /
// setTint) against the real index.html, verifying the pure hud.js decisions are
// applied correctly to the page. The MediaPipe CDN import is stubbed by the
// registered loader; browser globals are mocked so importing app.js (which
// self-initialises) is side-effect-free here.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { MockWebSocket } from "./mocks.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "..", "index.html"), "utf8");

let NOW = 1000;
let app;
let $;

before(async () => {
  const dom = new JSDOM(html, { url: "http://localhost/" });
  const { window } = dom;
  globalThis.window = window;
  globalThis.document = window.document;
  globalThis.Node = window.Node; // app.js's el() helper does `instanceof Node`
  globalThis.localStorage = window.localStorage;
  globalThis.WebSocket = MockWebSocket;
  globalThis.requestAnimationFrame = () => 0;
  // No token in localStorage → app.js's init() just shows the auth view (no fetch),
  // but the page loaders still call fetch, so return safe empty shapes.
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      assignments: [], workouts: [], patients: [], contacts: [], users: [],
      items: [], total: 0, count: 0, by_role: {}, total_users: 0,
      muscles: [], categories: [], difficulties: [],
    }),
  });
  Object.defineProperty(globalThis, "performance", {
    value: { now: () => NOW }, configurable: true, writable: true,
  });
  app = await import("../app.js");
  $ = (id) => window.document.getElementById(id);
});

test("showPage reveals the requested panel and hides the others", () => {
  const panel = (name) => document.querySelector(`[data-page="${name}"]`);
  app.showPage("scores", "scores");
  assert.equal(panel("scores").hidden, false);
  assert.equal(panel("messages").hidden, true);
  app.showPage("messages", "messages");
  assert.equal(panel("messages").hidden, false);
  assert.equal(panel("scores").hidden, true);
});

test("renderAnalysis applies a completed rep: count, feedback, faults, set label, metrics", () => {
  app.resetHudState();
  NOW = 1000;
  app.renderAnalysis({
    pose_visible: true, rep_count: 1, state: "up", rep_score: 80,
    feedback: "Squat deeper",
    form_issues: [{ message: "Squat deeper — aim for at least parallel" }],
    metrics: { knee_angle: 95, torso_lean: 30, knee_asymmetry: 0 },
    session: { completed_sets: 0, current_set_reps: 1, target_sets: 3, target_reps: 12 },
    deviation: 0,
  });
  assert.equal($("rep-count").textContent, "1");
  assert.equal($("feedback").textContent, "Squat deeper");
  assert.equal($("issues").children.length, 1);
  assert.equal($("last-score").textContent, "Last rep: 80");
  assert.equal($("set-info").textContent, "Set 1 / 3 · rep 1/12");
  // the hidden knee_asymmetry metric is not shown as a readout row
  const labels = [...$("metrics").querySelectorAll("dt")].map((n) => n.textContent);
  assert.deepEqual(labels, ["Knee", "Torso lean"]);
});

test("renderAnalysis clears the previous rep's faults once the next descent begins", () => {
  app.resetHudState();
  NOW = 1000;
  const session = { completed_sets: 0, current_set_reps: 1, target_sets: 3, target_reps: 12 };
  app.renderAnalysis({
    pose_visible: true, rep_count: 1, state: "up", rep_score: 80,
    feedback: "Squat deeper", form_issues: [{ message: "fault" }], metrics: {}, session, deviation: 0,
  });
  assert.equal($("issues").children.length, 1);
  NOW = 1100; // within the 3s hold, but now descending into the next rep
  app.renderAnalysis({
    pose_visible: true, rep_count: 1, state: "down", rep_score: null,
    feedback: "Sit back and down", metrics: {}, session, deviation: 0.5,
  });
  assert.equal($("issues").children.length, 0, "stale faults cleared on descent");
  assert.equal($("feedback").textContent, "Sit back and down");
});

test("renderAnalysis holds the panel through a brief dropout and clears after a sustained one", () => {
  app.resetHudState();
  NOW = 1000;
  const session = { completed_sets: 0, current_set_reps: 0, target_sets: null, target_reps: null };
  app.renderAnalysis({
    pose_visible: true, rep_count: 0, state: "up", rep_score: null,
    feedback: "", metrics: { knee_angle: 120 }, session, deviation: 0,
  });
  assert.ok($("metrics").children.length > 0);
  for (let i = 0; i < 5; i++) app.renderAnalysis({ pose_visible: false, rep_count: 0, feedback: "x" });
  assert.ok($("metrics").children.length > 0, "metrics held during a brief (<8 frame) dropout");
  const lost = "Step back so your whole body is visible in frame.";
  for (let i = 0; i < 5; i++) app.renderAnalysis({ pose_visible: false, rep_count: 0, feedback: lost });
  assert.equal($("metrics").children.length, 0, "metrics cleared after a sustained dropout");
  assert.equal($("feedback").textContent, lost);
});

test("setTint maps the deviation onto the #tint overlay", () => {
  app.setTint(0);
  assert.equal($("tint").style.opacity, "0");
  app.setTint(1);
  // the DOM normalises "0.500" → "0.5" on read-back (as browsers do); the exact
  // string form is asserted on the pure tintStyle() in hud.test.mjs.
  assert.equal(parseFloat($("tint").style.opacity), 0.5);
});
