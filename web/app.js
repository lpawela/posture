// Posture front-end controller: auth, role dashboards, monitored workout,
// scores and messaging. Talks to the REST API and drives PoseWorkout for the
// live camera session.

import { PoseWorkout, cameraErrorMessage } from "./pose.js";
import {
  SETUP_HINT,
  setInfoText,
  smoothDeviation,
  tintStyle,
  decideFeedback,
  navActionFor,
} from "./hud.js";

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    node.append(c instanceof Node ? c : document.createTextNode(c));
  }
  return node;
}

function fmtDate(epoch) {
  return new Date(epoch * 1000).toLocaleString();
}

// --- API client ---------------------------------------------------------- //

const api = {
  token: localStorage.getItem("posture_token") || null,
  user: JSON.parse(localStorage.getItem("posture_user") || "null"),
  setSession(token, user) {
    this.token = token;
    this.user = user;
    localStorage.setItem("posture_token", token);
    localStorage.setItem("posture_user", JSON.stringify(user));
  },
  clear() {
    this.token = this.user = null;
    localStorage.removeItem("posture_token");
    localStorage.removeItem("posture_user");
  },
  async req(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    if (this.token) headers.Authorization = "Bearer " + this.token;
    const res = await fetch(path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error((data && (data.detail || data.message)) || res.statusText);
    return data;
  },
  get(p) { return this.req("GET", p); },
  post(p, b) { return this.req("POST", p, b); },
};

const PAGES = {
  patient: [["assignments", "My exercises"], ["catalog", "Exercise library"], ["scores", "My scores"], ["messages", "Messages"]],
  doctor: [["patients", "Patients"], ["catalog", "Exercise library"], ["messages", "Messages"]],
  admin_basic: [["admin-users", "Users"]],
  admin_super: [["admin-users", "Users"], ["admin-create", "Admin accounts"]],
};

const isSuperAdmin = () => api.user && api.user.role === "admin_super";

let exercisesMeta = {};
let workout = null;
let selectedContact = null;
let selectedPatient = null;

// Live-workout HUD state (reset whenever a session (re)starts). The pure logic
// that operates on this state lives in hud.js; here we only hold it and apply
// the results to the DOM.
let smoothedDeviation = 0;   // EMA of the out-of-bounds deviation → steadier tint
let missCount = 0;           // consecutive pose-not-visible frames
let feedbackHoldUntil = 0;   // keep a rep's feedback on screen until this time
let lastRepCount = 0;        // latest cumulative rep count this session
let workoutRecording = false; // server will persist this session (patient + assignment)

function resetHudState() {
  smoothedDeviation = 0;
  missCount = 0;
  feedbackHoldUntil = 0;
  lastRepCount = 0;
  // NOTE: workoutRecording is deliberately NOT reset here. It reflects the
  // connection's recording capability (set by onReady) and must survive a
  // mid-session Reset; otherwise a post-reset workout would be discarded rather
  // than finished on nav-away. The nav-away guard also requires workout.isOpen(),
  // so a stale `true` on a closed socket can't trigger a spurious finish.
}

// --- view switching ------------------------------------------------------ //

// `highlight` is the nav tab to mark active — defaults to `name`, but the
// workout sub-page (which has no tab of its own) passes its originating page so
// the nav doesn't go blank.
function showPage(name, highlight = name) {
  // Leaving the workout page must release the camera / WebSocket; otherwise the
  // session keeps streaming (and burning battery) behind a hidden overlay. If a
  // recordable session with reps is in progress, FINISH it (which persists the
  // workout, then releases the camera via onSummary) rather than discarding it.
  if (name !== "workout" && workout) {
    const action = navActionFor({ recording: workoutRecording, reps: lastRepCount, open: workout.isOpen() });
    if (action === "finish") {
      // Persist the partial workout AND release the camera now (don't wait on a
      // server reply that might never arrive); then clear the gate so a second
      // nav before the summary lands just stops.
      workout.finishAndRelease();
      workoutRecording = false;
      lastRepCount = 0;
    } else {
      workout.stop();
    }
  }
  document.querySelectorAll(".panel-page").forEach((p) => {
    p.hidden = p.dataset.page !== name;
  });
  document.querySelectorAll(".nav .tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.page === highlight);
  });
  if (name === "assignments") loadAssignments();
  if (name === "scores") loadMyScores();
  if (name === "patients") loadPatients();
  if (name === "messages") loadContacts();
  if (name === "admin-users") loadAdminUsers();
  if (name === "catalog") loadCatalog();
}

function buildNav() {
  const nav = $("nav");
  nav.innerHTML = "";
  for (const [page, label] of PAGES[api.user.role]) {
    nav.append(el("button", { class: "tab", "data-page": page, onclick: () => showPage(page) }, label));
  }
}

async function enterApp() {
  exercisesMeta = {};
  try {
    const data = await api.get("/api/exercises");
    for (const ex of data.exercises) exercisesMeta[ex.name] = ex;
  } catch (e) { /* metadata is non-critical */ }

  $("auth-view").hidden = true;
  $("app-view").hidden = false;
  $("whoami").textContent = `${api.user.display_name} · ${api.user.role}`;
  $("logout").hidden = false;
  buildNav();
  showPage(PAGES[api.user.role][0][0]);
}

// --- auth ---------------------------------------------------------------- //

let authMode = "login";

document.querySelectorAll(".tab[data-tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    authMode = tab.dataset.tab;
    document.querySelectorAll(".tab[data-tab]").forEach((t) => t.classList.toggle("active", t === tab));
    $("register-fields").hidden = authMode !== "register";
    $("auth-submit").textContent = authMode === "register" ? "Create account" : "Log in";
  });
});

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("auth-error").textContent = "";
  const username = $("f-username").value.trim();
  const password = $("f-password").value;
  try {
    let out;
    if (authMode === "register") {
      out = await api.post("/api/auth/register", {
        username,
        password,
        display_name: $("f-display").value.trim() || username,
        role: $("f-role").value,
      });
    } else {
      out = await api.post("/api/auth/login", { username, password });
    }
    api.setSession(out.token, out.user);
    await enterApp();
  } catch (err) {
    $("auth-error").textContent = err.message;
  }
});

$("logout").addEventListener("click", async () => {
  const btn = $("logout");
  if (btn.disabled) return;        // ignore double-clicks
  btn.disabled = true;
  if (workout) workout.stop();
  // Best-effort server-side token revoke, bounded so a stalled request can't
  // hang logout — we always fall through to clear local state and reload.
  await Promise.race([
    api.post("/api/auth/logout").catch(() => {}),
    new Promise((r) => setTimeout(r, 1500)),
  ]);
  api.clear();
  location.reload();
});

// --- patient: assignments ------------------------------------------------ //

async function loadAssignments() {
  const { assignments } = await api.get("/api/me/assignments");
  const list = $("assignment-list");
  list.innerHTML = "";
  $("assignment-empty").hidden = assignments.length > 0;
  for (const a of assignments) {
    list.append(
      el("li", { class: "list-item" }, [
        el("div", {}, [
          el("strong", {}, exercisesMeta[a.exercise]?.display_name || a.exercise),
          el("div", { class: "muted" }, `${a.target_sets} sets × ${a.target_reps} reps${a.notes ? " — " + a.notes : ""}`),
        ]),
        el("button", { class: "btn btn-primary btn-small", onclick: () => startWorkout(a) }, "Start"),
      ])
    );
  }
}

// --- patient: monitored workout ------------------------------------------ //

function ensureWorkout() {
  if (workout) return workout;
  workout = new PoseWorkout({
    video: $("video"),
    canvas: $("overlay"),
    onStatus: (s) => ($("status").textContent = s),
    onReady: (m) => {
      workoutRecording = !!m.recording;
      $("status").textContent = m.recording
        ? "Tracking — this workout will be saved for your doctor."
        : "Tracking — live feedback only (not recorded).";
    },
    onAnalysis: renderAnalysis,
    onSetComplete: (m) => ($("set-info").textContent = setInfoText(m)),
    onSummary: renderSummary,
    onClosed: () => {
      // The live socket closed unexpectedly (network drop, or a finish whose
      // summary never arrived). Reset the controls so the user can start again
      // rather than being stuck with Start disabled.
      workoutRecording = false;
      lastRepCount = 0;
      $("start").disabled = false;
      ["end-set", "finish", "reset"].forEach((id) => ($(id).disabled = true));
      setTint(0);
    },
  });
  return workout;
}

// Tint the video overlay from clear (in bounds) to yellow and on to red as the
// live form deviation (0..1) grows.
function setTint(deviation) {
  const tint = document.getElementById("tint");
  if (!tint) return;
  const { backgroundColor, opacity } = tintStyle(deviation);
  tint.style.backgroundColor = backgroundColor;
  tint.style.opacity = opacity;
}

// Small debug hook (handy for manual/automated UI checks of the tint).
if (typeof window !== "undefined") window.__posture = { setTint };

const METRIC_LABELS = {
  knee_angle: "Knee",
  hip_angle: "Hip",
  torso_lean: "Torso lean",
};
// Metrics that drive the live tint but aren't shown as a readout row (e.g.
// knee_asymmetry is only present on front-on frames, so a row would blink
// in/out as the far leg's visibility wavers).
const HIDDEN_METRICS = new Set(["knee_asymmetry"]);

function renderAnalysis(msg) {
  $("rep-count").textContent = msg.rep_count;

  // Brief tracking dropouts (a landmark dipping below the visibility threshold
  // for a frame or two) shouldn't blank the panel and clear the warning tint.
  // Hold the last good display; only show "step into frame" after a sustained
  // loss of tracking.
  if (msg.pose_visible === false) {
    if (++missCount < 8) return; // ~0.25s at 30fps
    smoothedDeviation = 0;
    setTint(0);
    $("metrics").innerHTML = "";
    // Don't stomp a just-completed rep's feedback that's still within its hold;
    // clear the feedback line and its matching fault cues together once it does.
    if (performance.now() >= feedbackHoldUntil) {
      $("feedback").textContent = msg.feedback || SETUP_HINT;
      $("issues").innerHTML = "";
    }
    return;
  }
  missCount = 0;
  lastRepCount = msg.rep_count;

  // Smooth the deviation so a noisy frame near the threshold doesn't flicker the
  // tint; the mapping + EMA + clear-when-in-bounds logic lives in hud.js.
  smoothedDeviation = smoothDeviation(smoothedDeviation, msg.deviation);
  setTint(smoothedDeviation);

  $("set-info").textContent = setInfoText(msg.session || {});

  // The feedback line + fault-cue latch is decided purely in hud.js; here we
  // just apply the directive to the DOM.
  const fb = decideFeedback(msg, performance.now(), feedbackHoldUntil);
  feedbackHoldUntil = fb.holdUntil;
  if (fb.rebuildIssues) {
    $("last-score").textContent = `Last rep: ${msg.rep_score}`;
    $("feedback").textContent = fb.feedback;
    const issues = $("issues");
    issues.innerHTML = "";
    for (const i of msg.form_issues || []) issues.append(el("li", {}, i.message));
  } else if (fb.feedback != null) {
    $("feedback").textContent = fb.feedback;
    if (fb.clearIssues) $("issues").innerHTML = "";
  }

  const metrics = $("metrics");
  metrics.innerHTML = "";
  for (const [k, v] of Object.entries(msg.metrics || {})) {
    if (HIDDEN_METRICS.has(k)) continue;
    metrics.append(el("dt", {}, METRIC_LABELS[k] || k), el("dd", {}, `${v}°`));
  }
}

function renderSummary(msg) {
  const box = $("summary");
  box.hidden = false;
  box.innerHTML = "";
  box.append(
    el("h3", {}, "Workout complete"),
    el("div", { class: "summary-grid" }, [
      summaryStat("Overall", msg.overall_score),
      summaryStat("Form", msg.form_score),
      summaryStat("Sets", msg.total_sets),
      summaryStat("Reps", msg.total_reps),
      summaryStat("Completion", msg.completion_ratio != null ? Math.round(msg.completion_ratio * 100) + "%" : "—"),
    ]),
    el("div", { class: "muted" }, "Set scores: " + (msg.set_scores.join(", ") || "—"))
  );
  ["end-set", "finish", "reset"].forEach((id) => ($(id).disabled = true));
  $("start").disabled = false;
  $("status").textContent = "Workout complete.";
  workoutRecording = false;
  resetHudState();
  setTint(0);
  if (workout) workout.stop();
}

function summaryStat(label, value) {
  return el("div", { class: "summary-stat" }, [
    el("div", { class: "summary-value" }, String(value)),
    el("div", { class: "summary-label" }, label),
  ]);
}

function resetWorkoutHud(assignment) {
  const init = {
    completed_sets: 0,
    current_set_reps: 0,
    target_sets: assignment.target_sets,
    target_reps: assignment.target_reps,
  };
  $("set-info").textContent = setInfoText(init);
  $("rep-count").textContent = "0";
  $("last-score").textContent = "Last rep: —";
  $("feedback").textContent = SETUP_HINT;
  $("issues").innerHTML = "";
  $("metrics").innerHTML = "";
  resetHudState();
  setTint(0);
}

async function startWorkout(assignment) {
  // The workout sub-page has no nav tab; keep "My exercises" highlighted.
  showPage("workout", "assignments");
  $("summary").hidden = true;
  $("workout-title").textContent =
    (exercisesMeta[assignment.exercise]?.display_name || assignment.exercise) +
    ` — ${assignment.target_sets} × ${assignment.target_reps}`;
  const ref = exercisesMeta[assignment.exercise]?.reference_video;
  const link = $("reference-link");
  if (ref) {
    link.hidden = false;
    link.href = ref.url;
    link.textContent = "▶ Reference: " + ref.title;
  } else link.hidden = true;

  resetWorkoutHud(assignment);
  // Start is re-enabled here so a session can be (re)started after navigating
  // away mid-workout (which stops the previous session).
  $("start").disabled = false;
  ["end-set", "finish", "reset"].forEach((id) => ($(id).disabled = true));

  // Heads-up before they even press Start if the page can't use the camera.
  if (!window.isSecureContext) {
    $("status").textContent =
      "Camera needs HTTPS — open this app at https://… (or localhost) to enable it.";
  }

  const w = ensureWorkout();
  $("start").onclick = async () => {
    $("start").disabled = true;
    resetHudState();
    setTint(0);
    try {
      await w.start({ assignmentId: assignment.id, exercise: assignment.exercise, token: api.token });
      ["end-set", "finish", "reset"].forEach((id) => ($(id).disabled = false));
    } catch (err) {
      $("status").textContent = cameraErrorMessage(err);
      $("start").disabled = false;
    }
  };
  $("end-set").onclick = () => w.endSet();
  $("finish").onclick = () => {
    w.finishAndRelease();
    // Session is ending: clear the nav-away gate (so a nav before the summary
    // can't re-finish) and lock the action buttons (no stray commands in the
    // finish→summary window). renderSummary re-enables Start when it arrives.
    workoutRecording = false;
    lastRepCount = 0;
    ["end-set", "finish", "reset"].forEach((id) => ($(id).disabled = true));
  };
  $("reset").onclick = () => {
    w.reset();
    resetWorkoutHud(assignment);
    $("summary").hidden = true;
  };
}

// --- patient: my scores -------------------------------------------------- //

async function loadMyScores() {
  $("scores-title").textContent = "My scores";
  const { workouts } = await api.get("/api/me/workouts");
  renderScores(workouts);
}

function renderScores(workouts) {
  const list = $("scores-list");
  list.innerHTML = "";
  $("scores-empty").hidden = workouts.length > 0;
  for (const w of workouts.slice().reverse()) {
    list.append(
      el("li", { class: "list-item" }, [
        el("div", {}, [
          el("strong", {}, `${exercisesMeta[w.exercise]?.display_name || w.exercise} — score ${w.overall_score}`),
          el("div", { class: "muted" }, `${w.total_sets} sets · ${w.total_reps} reps · form ${w.form_score} · ${fmtDate(w.created_at)}`),
        ]),
        el("div", { class: "score-badge" }, String(w.overall_score)),
      ])
    );
  }
}

// --- doctor: patients ---------------------------------------------------- //

$("add-patient-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("add-patient-username").value.trim();
  if (!username) return;
  try {
    await api.post("/api/doctor/patients", { patient_username: username });
    $("add-patient-username").value = "";
    loadPatients();
  } catch (err) {
    alert("Could not add patient: " + err.message);
  }
});

async function loadPatients() {
  const { patients } = await api.get("/api/doctor/patients");
  const list = $("patient-list");
  list.innerHTML = "";
  for (const p of patients) {
    list.append(
      el("li", { class: "list-item" }, [
        el("div", {}, [el("strong", {}, p.display_name), el("div", { class: "muted" }, "@" + p.username)]),
        el("div", {}, [
          el("button", { class: "btn btn-small", onclick: () => openAssign(p) }, "Assign"),
          el("button", { class: "btn btn-small", onclick: () => viewPatientScores(p) }, "Scores"),
        ]),
      ])
    );
  }
}

function openAssign(patient) {
  selectedPatient = patient;
  $("assign-box").hidden = false;
  $("assign-title").textContent = `Assign exercise to ${patient.display_name}`;
  const sel = $("assign-exercise");
  sel.innerHTML = "";
  for (const name of Object.keys(exercisesMeta)) {
    sel.append(el("option", { value: name }, exercisesMeta[name].display_name));
  }
  $("assign-status").textContent = "";
}

$("assign-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!selectedPatient) return;
  try {
    await api.post("/api/assignments", {
      patient_id: selectedPatient.id,
      exercise: $("assign-exercise").value,
      target_sets: Number($("assign-sets").value),
      target_reps: Number($("assign-reps").value),
      notes: $("assign-notes").value.trim(),
    });
    $("assign-status").textContent = "Assigned ✓";
  } catch (err) {
    $("assign-status").textContent = "Error: " + err.message;
  }
});

async function viewPatientScores(patient) {
  const { workouts } = await api.get(`/api/doctor/patients/${patient.id}/workouts`);
  showPage("scores");
  $("scores-title").textContent = `Scores — ${patient.display_name}`;
  renderScores(workouts);
}

// --- exercise catalog (MuscleWiki library) ------------------------------- //

let catalogFiltersLoaded = false;
let catalogDebounce = null;

async function loadCatalogFilters() {
  if (catalogFiltersLoaded) return;
  const f = await api.get("/api/catalog/filters");
  const fill = (id, values) => {
    const sel = $(id);
    for (const v of values) sel.append(el("option", { value: v }, v));
  };
  fill("cat-muscle", f.muscles);
  fill("cat-category", f.categories);
  fill("cat-difficulty", f.difficulties);
  catalogFiltersLoaded = true;
}

async function loadCatalog() {
  await loadCatalogFilters();
  const params = new URLSearchParams({ limit: "60" });
  const q = $("cat-q").value.trim();
  if (q) params.set("q", q);
  for (const [id, key] of [["cat-muscle", "muscle"], ["cat-category", "category"], ["cat-difficulty", "difficulty"]]) {
    if ($(id).value) params.set(key, $(id).value);
  }
  const data = await api.get("/api/catalog?" + params.toString());
  $("cat-count").textContent =
    `${data.total} exercises` + (data.total > data.count ? ` (showing ${data.count})` : "");
  const list = $("cat-list");
  list.innerHTML = "";
  for (const e of data.items) {
    const sub = `${e.category}${e.difficulty ? " · " + e.difficulty : ""} · ${(e.primary_muscles || []).join(", ")}`;
    list.append(
      el("li", { class: "list-item", onclick: () => showCatalogDetail(e.slug) }, [
        el("div", {}, [el("strong", {}, e.name), el("div", { class: "muted" }, sub)]),
      ])
    );
  }
}

async function showCatalogDetail(slug) {
  const e = await api.get(`/api/catalog/${encodeURIComponent(slug)}`);
  const box = $("cat-detail");
  box.hidden = false;
  box.innerHTML = "";
  box.append(
    el("h3", {}, e.name),
    el("div", { class: "muted" }, `${e.category}${e.difficulty ? " · " + e.difficulty : ""}${e.force ? " · " + e.force : ""}`),
    el("div", { class: "muted" }, `Primary: ${(e.primary_muscles || []).join(", ") || "—"} · Secondary: ${(e.secondary_muscles || []).join(", ") || "—"}`)
  );
  if (e.video_urls && e.video_urls[0]) {
    box.append(el("video", { class: "cat-video", src: e.video_urls[0], controls: "", muted: "", loop: "", playsinline: "" }));
  }
  if ((e.steps || []).length) {
    const ol = el("ol", { class: "cat-steps" });
    e.steps.forEach((s) => ol.append(el("li", {}, s)));
    box.append(el("h4", {}, "Steps"), ol);
  }
}

["cat-muscle", "cat-category", "cat-difficulty"].forEach((id) => {
  const node = document.getElementById(id);
  if (node) node.addEventListener("change", loadCatalog);
});
const catQ = document.getElementById("cat-q");
if (catQ) {
  catQ.addEventListener("input", () => {
    clearTimeout(catalogDebounce);
    catalogDebounce = setTimeout(loadCatalog, 250);
  });
}

// --- admin: users & medical records -------------------------------------- //

async function loadAdminUsers() {
  $("admin-medical").hidden = true;
  const stats = await api.get("/api/admin/stats");
  const statsEl = $("admin-stats");
  statsEl.innerHTML = "";
  statsEl.append(el("span", { class: "chip" }, `${stats.total_users} users`));
  for (const [role, n] of Object.entries(stats.by_role)) {
    statsEl.append(el("span", { class: "chip" }, `${n} ${role}`));
  }

  const { users } = await api.get("/api/admin/users");
  const list = $("admin-user-list");
  list.innerHTML = "";
  for (const u of users) {
    const actions = [];
    if (isSuperAdmin()) {
      actions.push(el("button", { class: "btn btn-small", onclick: () => loadMedical(u) }, "Medical records"));
    }
    list.append(
      el("li", { class: "list-item" }, [
        el("div", {}, [el("strong", {}, u.display_name), el("div", { class: "muted" }, `@${u.username} · ${u.role}`)]),
        el("div", {}, actions),
      ])
    );
  }
}

async function loadMedical(u) {
  const data = await api.get(`/api/admin/users/${u.id}/medical`);
  const box = $("admin-medical");
  box.hidden = false;
  box.innerHTML = "";
  const docs = data.links.doctors.map((d) => d.display_name).join(", ") || "—";
  const pats = data.links.patients.map((p) => p.display_name).join(", ") || "—";
  box.append(
    el("h3", {}, `Medical records — ${u.display_name}`),
    el("div", { class: "muted" }, `Doctors: ${docs} · Patients: ${pats}`),
    el("h4", {}, "Assignments"),
    listOrNone(data.assignments, (a) => `${a.exercise} — ${a.target_sets}×${a.target_reps}${a.notes ? " · " + a.notes : ""}`),
    el("h4", {}, "Workout scores"),
    listOrNone(data.workouts, (w) => `${w.exercise} — overall ${w.overall_score} (${w.total_sets} sets, ${w.total_reps} reps, form ${w.form_score})`),
    el("h4", {}, "Messages"),
    listOrNone(data.messages, (m) => m.body)
  );
}

function listOrNone(items, fmt) {
  if (!items.length) return el("p", { class: "muted" }, "none");
  const ul = el("ul", { class: "list" });
  for (const it of items) ul.append(el("li", { class: "list-item" }, fmt(it)));
  return ul;
}

const createAdminForm = $("create-admin-form");
if (createAdminForm) {
  createAdminForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const out = await api.post("/api/admin/admins", {
        username: $("ca-username").value.trim(),
        password: $("ca-password").value,
        tier: $("ca-tier").value,
      });
      $("ca-status").textContent = `Created ${out.username} (${out.role}) ✓`;
      $("ca-username").value = "";
      $("ca-password").value = "";
    } catch (err) {
      $("ca-status").textContent = "Error: " + err.message;
    }
  });
}

// --- messaging ----------------------------------------------------------- //

async function loadContacts() {
  const { contacts } = await api.get("/api/contacts");
  const list = $("contact-list");
  list.innerHTML = "";
  for (const c of contacts) {
    list.append(
      el("li", {
        class: "contact" + (selectedContact === c.id ? " active" : ""),
        onclick: () => selectContact(c),
      }, c.display_name)
    );
  }
  if (contacts.length && selectedContact == null) selectContact(contacts[0]);
  else if (!contacts.length) $("thread-messages").innerHTML = '<p class="muted">No contacts yet.</p>';
}

async function selectContact(contact) {
  selectedContact = contact.id;
  document.querySelectorAll(".contact").forEach((c) => c.classList.toggle("active", c.textContent === contact.display_name));
  await loadThread();
}

async function loadThread() {
  if (selectedContact == null) return;
  const { messages } = await api.get(`/api/messages/${selectedContact}`);
  const box = $("thread-messages");
  box.innerHTML = "";
  for (const m of messages) {
    box.append(el("div", { class: "bubble " + (m.sender_id === api.user.id ? "mine" : "theirs") }, m.body));
  }
  box.scrollTop = box.scrollHeight;
}

$("message-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = $("message-body").value.trim();
  if (!body || selectedContact == null) return;
  try {
    await api.post("/api/messages", { recipient_id: selectedContact, body });
    $("message-body").value = "";
    loadThread();
  } catch (err) {
    alert("Could not send: " + err.message);
  }
});

// --- boot ---------------------------------------------------------------- //

(async function init() {
  if (api.token && api.user) {
    try {
      await api.get("/api/auth/me"); // validate token
      await enterApp();
      return;
    } catch {
      api.clear();
    }
  }
  $("auth-view").hidden = false;
})();

// Exported for the jsdom unit tests. Harmless in the browser: the page-entry
// module may declare exports; nothing imports app.js at runtime.
export { showPage, renderAnalysis, setTint, resetHudState };
