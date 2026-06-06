// Pure presentation / decision helpers for the live-workout HUD.
//
// These are intentionally DOM-free and side-effect-free so they can be unit
// tested in Node without a browser. app.js holds the (thin) DOM glue and the
// mutable session state; everything here is a pure function of its inputs.
// This is where the fiddly, regression-prone logic lives — the set/rep label,
// the tint mapping, the rep-feedback latch, and the navigate-away decision.

export const SETUP_HINT = "Stand side-on, full body in frame.";

// "Set X / N · rep R/M" for the HUD, from a session_state-shaped object
// ({completed_sets, current_set_reps, target_sets, target_reps}). The displayed
// set index is clamped to the target (never "Set 4 / 3"), a finished prescribed
// workout reads "complete", and free-form (null target) sessions show "—".
export function setInfoText(s) {
  const ts = s.target_sets ?? null;
  const tr = s.target_reps ?? null;
  if (ts != null && s.completed_sets >= ts && s.current_set_reps === 0) {
    return `Set ${ts} / ${ts} · complete`;
  }
  let cur = s.completed_sets + 1;
  if (ts != null) cur = Math.min(cur, ts);
  return `Set ${cur} / ${ts ?? "—"} · rep ${s.current_set_reps}/${tr ?? "—"}`;
}

// Exponential moving average of the out-of-bounds deviation, so a noisy frame
// near a threshold doesn't make the tint flicker. Tiny residuals snap to 0 so
// an in-bounds pose reads as fully clear (no lingering faint tint).
export function smoothDeviation(prev, raw) {
  const next = 0.5 * (raw || 0) + 0.5 * prev;
  return next < 0.01 ? 0 : next;
}

// CSS for the out-of-bounds tint at a deviation in [0, 1]: clear→yellow→red.
// Any deviation > 0 shows a faint tint that ramps up (no 2% dead-band that
// would hide early drift); exactly in-bounds is fully transparent.
export function tintStyle(deviation) {
  const v = Math.max(0, Math.min(1, deviation || 0));
  return {
    backgroundColor: `hsl(${Math.round(60 * (1 - v))}, 100%, 50%)`,
    opacity: v > 0 ? (0.08 + 0.42 * v).toFixed(3) : "0",
  };
}

// Decide what the feedback line + fault-cue list should do for one *visible*
// analysis frame, given the current time and the active hold deadline. Pure: it
// returns a directive that app.js applies to the DOM.
//
//   { feedback, rebuildIssues, clearIssues, latched, holdUntil }
//
// - feedback === null  → leave the feedback line as-is (within a hold, or the
//                        pre-first-rep setup hint).
// - rebuildIssues      → a rep just completed: show its score, rebuild the
//                        fault list from msg.form_issues, and latch (holdUntil).
// - clearIssues        → a live cue replaced the rep result: clear the stale faults.
export function decideFeedback(msg, now, holdUntil, holdMs = 3000) {
  if (msg.rep_score != null) {
    // A rep just completed: show its result + faults and hold them on screen so
    // they aren't overwritten by the generic live cue ~1 frame later.
    return {
      feedback: msg.feedback || "",
      rebuildIssues: true,
      clearIssues: false,
      latched: true,
      holdUntil: now + holdMs,
    };
  }
  if (msg.state === "down") {
    // Descending into the next rep: show the live cue immediately (releasing the
    // hold) and clear the previous rep's now-stale faults.
    return { feedback: msg.feedback || "", rebuildIssues: false, clearIssues: true, latched: false, holdUntil };
  }
  if (now >= holdUntil && msg.rep_count > 0) {
    // Between reps, after the hold elapsed: live cue, faults cleared.
    return { feedback: msg.feedback || "", rebuildIssues: false, clearIssues: true, latched: false, holdUntil };
  }
  // Within the hold, or standing before the first rep: keep what's shown.
  return { feedback: null, rebuildIssues: false, clearIssues: false, latched: false, holdUntil };
}

// On leaving the workout page: "finish" (persist the partial workout, then
// release the camera) only when a recordable session with at least one rep is
// still connected; otherwise just "stop".
export function navActionFor({ recording, reps, open }) {
  return recording && reps > 0 && open ? "finish" : "stop";
}
