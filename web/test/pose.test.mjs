// Unit tests for the PoseWorkout camera/WebSocket lifecycle (web/pose.js) — the
// part that has regressed in every review round. Browser APIs are mocked; the
// MediaPipe CDN import is stubbed by the registered loader (see register.mjs).
import { test } from "node:test";
import assert from "node:assert/strict";
import { MockWebSocket, makeStream, mockVideo, mockCanvas } from "./mocks.mjs";
import { PoseWorkout } from "../pose.js";

// Browser globals pose.js reaches for. requestAnimationFrame is a no-op so the
// predict loop never actually spins during a test.
globalThis.WebSocket = MockWebSocket;
globalThis.location = { protocol: "http:", host: "localhost" };
globalThis.requestAnimationFrame = () => 0;
globalThis.performance = globalThis.performance || { now: () => 0 };

function setup(opts = {}) {
  MockWebSocket.reset();
  let lastStream = null;
  globalThis.navigator = {
    mediaDevices: {
      getUserMedia: opts.getUserMedia || (async () => (lastStream = makeStream())),
    },
  };
  const events = { status: [], closed: 0, ready: [], summary: [] };
  const video = mockVideo(opts);
  const w = new PoseWorkout({
    video,
    canvas: mockCanvas(),
    onStatus: (s) => events.status.push(s),
    onClosed: () => events.closed++,
    onReady: (m) => events.ready.push(m),
    onSummary: (m) => events.summary.push(m),
  });
  return { w, video, events, lastStream: () => lastStream };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

test("start acquires the camera, opens a socket, and is running", async () => {
  const { w, video } = setup();
  await w.start({ exercise: "squat" });
  assert.ok(video.srcObject, "camera attached");
  assert.equal(w.running, true);
  assert.equal(MockWebSocket.instances.length, 1);
  assert.ok(w.isOpen());
});

test("stop releases the camera, stops tracks, and closes the socket", async () => {
  const { w, video } = setup();
  await w.start({ exercise: "squat" });
  const stream = video.srcObject;
  w.stop();
  assert.equal(video.srcObject, null);
  assert.equal(w.running, false);
  assert.ok(stream._tracks[0]._stopped, "camera track stopped");
  assert.equal(MockWebSocket.instances[0].readyState, MockWebSocket.CLOSED);
  assert.equal(w.isOpen(), false);
});

test("finishAndRelease sends finish, releases the camera, and keeps the socket open", async () => {
  const { w, video } = setup();
  await w.start({ exercise: "squat" });
  const ws = MockWebSocket.instances[0];
  w.finishAndRelease();
  assert.equal(video.srcObject, null, "camera released immediately");
  assert.equal(w.running, false);
  assert.deepEqual(ws.sentTypes(), ["finish"]);
  assert.equal(ws.readyState, MockWebSocket.OPEN, "socket left open to receive the summary");
});

test("an unexpected socket close releases the camera and notifies onClosed", async () => {
  const { w, video, events } = setup();
  await w.start({ exercise: "squat" });
  MockWebSocket.instances[0].fireClose();
  assert.equal(video.srcObject, null);
  assert.equal(events.closed, 1);
  assert.ok(events.status.includes("Disconnected."));
});

test("a server error message is not clobbered by 'Disconnected.' on close", async () => {
  const { w, events } = setup();
  await w.start({ exercise: "squat" });
  const ws = MockWebSocket.instances[0];
  ws.emit({ type: "error", message: "assignment not found or not yours" });
  ws.fireClose();
  assert.ok(events.status.some((s) => s.includes("assignment not found")));
  assert.ok(!events.status.includes("Disconnected."), "generic disconnect suppressed after a server error");
  assert.equal(events.closed, 1);
});

test("server messages are routed to the right callbacks", async () => {
  const { w, events } = setup();
  await w.start({ exercise: "squat" });
  const ws = MockWebSocket.instances[0];
  ws.emit({ type: "ready", recording: true, exercise: "squat" });
  ws.emit({ type: "summary", overall_score: 90 });
  assert.equal(events.ready.length, 1);
  assert.equal(events.ready[0].recording, true);
  assert.equal(events.summary.length, 1);
});

test("a failed start (play rejects) releases the camera and propagates", async () => {
  let stream;
  globalThis.navigator = {
    mediaDevices: { getUserMedia: async () => (stream = makeStream()) },
  };
  const video = mockVideo({ play: async () => { throw new Error("play failed"); } });
  const w = new PoseWorkout({ video, canvas: mockCanvas(), onStatus() {} });
  MockWebSocket.reset();
  await assert.rejects(() => w.start({ exercise: "squat" }), /play failed/);
  assert.equal(video.srcObject, null, "camera released on failure");
  assert.ok(stream._tracks[0]._stopped);
  assert.equal(w.running, false);
});

// The regression that recurred across rounds: on a restart, the OLD socket's
// onclose fires LATE (while the new session is still acquiring its camera).
// The generation guard must make that stale close a no-op, so it doesn't kill
// the new session's just-acquired camera.
test("a superseded socket's late close does not kill the restarted session's camera", async () => {
  MockWebSocket.reset();
  const streams = [];
  globalThis.navigator = {
    mediaDevices: { getUserMedia: async () => { const s = makeStream(); streams.push(s); return s; } },
  };
  let resolvePlay;
  const video = {
    srcObject: null, readyState: 0, currentTime: 0, videoWidth: 0, videoHeight: 0,
    classList: { toggle() {} },
    play: () => new Promise((r) => { resolvePlay = r; }),
  };
  const w = new PoseWorkout({ video, canvas: mockCanvas(), onStatus() {}, onClosed() {} });

  // Session 1: start fully.
  const p1 = w.start({ exercise: "squat" });
  await flush();
  resolvePlay();
  await p1;
  const wsA = MockWebSocket.instances[0];
  const stream1 = video.srcObject;
  assert.ok(stream1 && w.isOpen());

  // Session 2 (restart): start() calls stop() (closes wsA, bumps generation),
  // re-acquires the camera (stream2 attached), then awaits play() — pause here,
  // with the new camera set but the new socket not yet created.
  const p2 = w.start({ exercise: "squat" });
  await flush();
  const stream2 = video.srcObject;
  assert.ok(stream2 && stream2 !== stream1, "new camera attached before play resolves");

  // wsA's onclose fires LATE, mid-restart. It must be recognised as stale.
  wsA.fireClose();
  assert.equal(video.srcObject, stream2, "stale onclose must NOT release the new camera");

  resolvePlay();
  await p2;
  assert.ok(w.isOpen());
  assert.equal(video.srcObject, stream2);
});
