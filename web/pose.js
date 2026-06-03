// Camera + MediaPipe pose estimation + workout WebSocket, wrapped in a class.
//
// The browser runs PoseLandmarker locally and streams the 33 landmarks per
// frame to /ws/analyze. The server counts reps/sets, scores form, and (for an
// authenticated patient with an assignment) records the finished workout.

import {
  FilesetResolver,
  PoseLandmarker,
  DrawingUtils,
} from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs";

const WASM_BASE =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/" +
  "pose_landmarker_lite/float16/1/pose_landmarker_lite.task";

export class PoseWorkout {
  constructor({ video, canvas, onAnalysis, onSummary, onSetComplete, onStatus }) {
    this.video = video;
    this.canvas = canvas;
    this.onAnalysis = onAnalysis || (() => {});
    this.onSummary = onSummary || (() => {});
    this.onSetComplete = onSetComplete || (() => {});
    this.onStatus = onStatus || (() => {});
    this.landmarker = null;
    this.drawer = null;
    this.ws = null;
    this.running = false;
    this.facingMode = "user";
    this.lastVideoTime = -1;
  }

  async loadModel() {
    if (this.landmarker) return;
    this.onStatus("Loading pose model…");
    const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
    this.landmarker = await PoseLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
      runningMode: "VIDEO",
      numPoses: 1,
    });
    this.drawer = new DrawingUtils(this.canvas.getContext("2d"));
    this.onStatus("Model ready.");
  }

  _wsUrl({ exercise, assignmentId, token }) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const params = new URLSearchParams();
    if (assignmentId != null) params.set("assignment_id", assignmentId);
    if (exercise) params.set("exercise", exercise);
    if (token) params.set("token", token);
    return `${proto}://${location.host}/ws/analyze?${params.toString()}`;
  }

  async start({ exercise, assignmentId, token } = {}) {
    // 1) Acquire the camera FIRST, while still inside the click's user gesture.
    //    Awaiting a slow model download before this can make iOS/Safari drop
    //    the permission prompt entirely.
    this.onStatus("Requesting camera…");
    const stream = await this._getCamera();
    this.video.srcObject = stream;
    const mirror = this.facingMode === "user";
    this.video.classList.toggle("mirror", mirror);
    this.canvas.classList.toggle("mirror", mirror);
    await this.video.play();

    // 2) Then load the pose model and open the analysis socket.
    this.onStatus("Loading pose model…");
    await this.loadModel();
    this.ws = new WebSocket(this._wsUrl({ exercise, assignmentId, token }));
    this.ws.onmessage = (e) => this._onMessage(JSON.parse(e.data));
    this.ws.onclose = () => { if (this.running) this.onStatus("Disconnected."); };

    this.running = true;
    this.onStatus("Tracking…");
    requestAnimationFrame(() => this._predict());
  }

  async _getCamera() {
    const md = navigator.mediaDevices;
    if (!md || !md.getUserMedia) {
      // The most common cause: a non-secure origin (plain http on a LAN IP).
      throw new Error(
        window.isSecureContext
          ? "This browser doesn't expose a camera API."
          : "The camera needs a secure page — open the app over HTTPS (https://…) or via localhost."
      );
    }
    // Use *ideal* (not exact) constraints so a missing front/back camera or
    // unsupported resolution doesn't reject the whole request.
    const video = { width: { ideal: 1280 }, height: { ideal: 720 } };
    try {
      return await md.getUserMedia({
        video: { ...video, facingMode: { ideal: this.facingMode } },
        audio: false,
      });
    } catch (err) {
      if (err && (err.name === "OverconstrainedError" || err.name === "NotFoundError")) {
        return await md.getUserMedia({ video: true, audio: false }); // any camera
      }
      throw err;
    }
  }

  _onMessage(msg) {
    if (msg.type === "analysis") this.onAnalysis(msg);
    else if (msg.type === "summary") this.onSummary(msg);
    else if (msg.type === "set_complete") this.onSetComplete(msg);
    else if (msg.type === "error") this.onStatus("Server: " + msg.message);
  }

  _predict() {
    if (!this.running) return;
    const v = this.video;
    if (v.readyState >= 2 && v.currentTime !== this.lastVideoTime) {
      this.lastVideoTime = v.currentTime;
      this.canvas.width = v.videoWidth;
      this.canvas.height = v.videoHeight;
      const result = this.landmarker.detectForVideo(v, performance.now());
      this._draw(result);
      this._send(result);
    }
    requestAnimationFrame(() => this._predict());
  }

  _draw(result) {
    const ctx = this.canvas.getContext("2d");
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    for (const lms of result.landmarks || []) {
      this.drawer.drawConnectors(lms, PoseLandmarker.POSE_CONNECTIONS, {
        color: "#38bdf8",
        lineWidth: 3,
      });
      this.drawer.drawLandmarks(lms, { color: "#f8fafc", radius: 3 });
    }
  }

  _send(result) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const lms = result.landmarks && result.landmarks[0];
    if (!lms) return;
    const landmarks = lms.map((p) => ({
      x: p.x, y: p.y, z: p.z ?? 0, visibility: p.visibility ?? 1,
    }));
    this.ws.send(JSON.stringify({ landmarks }));
  }

  _command(type) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type }));
    }
  }

  endSet() { this._command("end_set"); }
  reset() { this._command("reset"); }
  finish() { this._command("finish"); }

  stop() {
    this.running = false;
    if (this.ws) this.ws.close();
    const tracks = this.video.srcObject?.getTracks() || [];
    tracks.forEach((t) => t.stop());
    this.video.srcObject = null;
  }
}

/** Turn a getUserMedia error into a clear, actionable message. */
export function cameraErrorMessage(err) {
  switch (err && err.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Camera access was blocked. Allow the camera for this site in your browser settings, then press Start again.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No usable camera was found on this device.";
    case "NotReadableError":
      return "The camera is already in use by another app. Close it and try again.";
    default:
      return (err && err.message) || "Could not access the camera.";
  }
}
