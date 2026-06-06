// Module-customization hooks: pose.js statically imports the MediaPipe vision
// bundle from a jsdelivr HTTPS URL. Node's ESM loader can't fetch HTTPS imports,
// and the tests don't exercise real pose estimation, so we resolve that URL to a
// tiny in-memory stub module exporting the three symbols pose.js destructures.

const STUB_URL = "stub:mediapipe-tasks-vision";

const SOURCE = `
export class FilesetResolver {
  static async forVisionTasks() { return {}; }
}
export class PoseLandmarker {
  static POSE_CONNECTIONS = [];
  static async createFromOptions() {
    return { detectForVideo: () => ({ landmarks: [] }) };
  }
}
export class DrawingUtils {
  constructor() {}
  drawConnectors() {}
  drawLandmarks() {}
}
`;

export async function resolve(specifier, context, next) {
  if (specifier.startsWith("https://cdn.jsdelivr.net/")) {
    return { url: STUB_URL, shortCircuit: true };
  }
  return next(specifier, context);
}

export async function load(url, context, next) {
  if (url === STUB_URL) {
    return { format: "module", shortCircuit: true, source: SOURCE };
  }
  return next(url, context);
}
