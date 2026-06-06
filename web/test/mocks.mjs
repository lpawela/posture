// Shared test doubles for the browser APIs the client touches.

// A controllable WebSocket: starts OPEN, records sent frames, and only fires
// onclose / delivers messages when the test explicitly asks (so close races can
// be reproduced deterministically).
export class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];
  static reset() {
    MockWebSocket.instances = [];
  }

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.OPEN; // treat as connected for tests
    this.sent = [];
    this.onmessage = null;
    this.onclose = null;
    MockWebSocket.instances.push(this);
  }

  send(data) {
    this.sent.push(data);
  }

  // close() marks the socket closed but does NOT synchronously fire onclose —
  // matching the browser, where onclose is dispatched on a later task. Tests
  // drive the close callback via fireClose() at the moment they want.
  close() {
    this.readyState = MockWebSocket.CLOSED;
  }

  // --- test helpers ---
  emit(obj) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) });
  }
  fireClose() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose({});
  }
  sentTypes() {
    return this.sent.map((s) => JSON.parse(s).type).filter(Boolean);
  }
}

export function makeStream() {
  const tracks = [{ _stopped: false, kind: "video", stop() { this._stopped = true; } }];
  return { _tracks: tracks, getTracks: () => tracks, getVideoTracks: () => tracks };
}

export function mockVideo({ play } = {}) {
  return {
    srcObject: null,
    readyState: 0,
    currentTime: 0,
    videoWidth: 0,
    videoHeight: 0,
    classList: { toggle() {} },
    play: play || (async () => {}),
  };
}

export function mockCanvas() {
  return {
    width: 0,
    height: 0,
    classList: { toggle() {} },
    getContext: () => ({ clearRect() {} }),
  };
}
