/* Sabha: the app's main views in the design GPT-6.1 Sol made for it (the sabha-ui-preview).
   The markup and class names follow that design exactly (sabha.css); the data is the real project state.
   app.js still owns the state, the actions, the routes and the detail panels (task, review, an AI, adding
   an AI, switching projects, setup), which render inside .legacy so their styles never collide.
   Loaded after app.js; its functions are globals shared with it. */

const SB_PATHS = {
  search: '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/>',
  room: '<path d="M4 10.2 12 4l8 6.2V20h-5v-6H9v6H4z"/>',
  council: '<circle cx="12" cy="12" r="4"/><circle cx="12" cy="3" r="1.5"/><circle cx="4.2" cy="16.5" r="1.5"/><circle cx="19.8" cy="16.5" r="1.5"/><path d="M5.5 7a8.3 8.3 0 0 0-1.3 4M9 20a8.2 8.2 0 0 0 6 0M19.8 11A8.3 8.3 0 0 0 18.5 7"/>',
  plan: '<rect x="5" y="5" width="15" height="16" rx="2"/><path d="M9 3h7v4H9zM9 12h7M9 16h5"/>',
  review: '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  settings: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 16.5v.1"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  bell: '<path d="M5 16h14l-2-3V9a5 5 0 0 0-10 0v4zM10 20h4"/>',
  pause: '<path d="M9 5v14M15 5v14"/>',
  play: '<path d="m8 5 11 7-11 7z"/>',
  check: '<path d="m5 12 4.5 4.5L19 7"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  up: '<path d="M12 19V5m-6 6 6-6 6 6"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  spark: '<path d="M12 3c.6 4.8 2.2 6.4 7 7-4.8.6-6.4 2.2-7 7-.6-4.8-2.2-6.4-7-7 4.8-.6 6.4-2.2 7-7Z"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3M13 15h4"/>',
  file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h4"/>',
  git: '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/><path d="M6 7v10M8 17h2a8 8 0 0 0 8-8"/>',
  lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  book: '<path d="M12 5C9 3 5 3 3 4v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-2-1-6-1-9 1zm0 0v15"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
  grid: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.1M3 12h.1M3 18h.1"/>',
  folder: '<path d="M3 7V5h7l2 3h9v12H3z"/>',
  refresh: '<path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/>',
  message: '<path d="M4 4h16v13H9l-5 4zM8 8h8M8 12h5"/>',
  external: '<path d="M13 4h7v7M20 4 9 15M10 4H4v16h16v-6"/>',
  leaf: '<path d="M20 3C8 2 3 7 5 14c2 7 14 6 15-11ZM4 21 15 10"/>',
  alert: '<path d="M12 4l9 15.5H3z"/><path d="M12 10v4M12 17v.01"/>',
  x: '<path d="m6 6 12 12M18 6 6 18"/>',
};
function pi(name, cls) {
  return `<svg class="icon ${cls || ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${SB_PATHS[name] || SB_PATHS.room}</svg>`;
}
const esc = v => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SB_APP = { "claude-code": "Claude Code", "claude-vscode": "Claude Code", "claude-app": "Claude app", "codex-cli": "Codex CLI", "codex-vscode": "Codex",
  "codex-app": "ChatGPT app", "gemini-cli": "Gemini CLI", "qwen-code": "Qwen Code", opencode: "opencode", "copilot-cli": "Copilot CLI", cursor: "Cursor", other: "MCP app" };
const sbApp = app => SB_APP[app] || app;
/* markdown in a one-line preview: the words, without the marks */
const sbPlain = text => plainText(String(text || "").replace(/```[\s\S]*?```/g, " … ").replace(/`([^`]*)`/g, "$1").replace(/\*\*|__|^#+\s*/gm, "")).replace(/\s+/g, " ").trim();
const SB_VIEWS = ["room", "council", "plan", "reviews", "activity", "settings"];
const SB_NAME = { room: "The room", council: "Ask the table", plan: "Plan & tasks", reviews: "Reviews", activity: "Activity", settings: "Settings" };
const SB_HASH = { room: "#/room", council: "#/council", plan: "#/plan", reviews: "#/reviews", activity: "#/activity", settings: "#/settings" };

/* which main view is showing (the detail panels open over the view you were on) */
function sbView() {
  const p = route.page === "q" ? "council" : route.page;
  if (SB_VIEWS.includes(p)) return p;
  return ui.underView || "room";
}

/* pieces filled in after the HTML is in place: markdown, and the app's own (legacy) blocks */
let SB_SLOTS = {};
function slot(fn, cls) {
  const key = "s" + Object.keys(SB_SLOTS).length;
  SB_SLOTS[key] = fn;
  return `<div class="${cls || ""}" data-slot="${key}"></div>`;
}
function mdSlot(text) { return slot(() => md(String(text || "")), "md-body"); }
function fillSlots(root) {
  root.querySelectorAll("[data-slot]").forEach(el => {
    const fn = SB_SLOTS[el.dataset.slot];
    if (!fn) return;
    const out = fn();
    if (out == null) { el.remove(); return; }
    (Array.isArray(out) ? out.flat(9) : [out]).filter(Boolean).forEach(n => el.append(typeof n === "string" ? document.createTextNode(n) : n));
  });
  SB_SLOTS = {};
}

/* ---------------------------------------------------------------- small pieces of the design */

function sbHeading(eyebrow, title, subtitle, actions) {
  return `<div class="page-heading"><div><div class="eyebrow">${eyebrow}</div><h1>${title}<span class="title-period">.</span></h1><p>${subtitle}</p></div><div class="page-actions">${actions || ""}</div></div>`;
}
function sbBtn(text, action, style, ic, extra) {
  return `<button class="btn ${style || "secondary"}" data-action="${action}" ${extra || ""}>${ic ? pi(ic) : ""}${text}</button>`;
}
function sbAvatarClass(handle) {
  if (handle === "human") return "human";
  const x = seatOf(handle);
  const c = x ? x.company : "";
  return c === "anthropic" ? "claude" : c === "openai" ? "codex" : "qwen";
}
function sbAvatar(handle, cls) {
  if (handle === "human") return `<span class="avatar human ${cls || ""}" aria-hidden="true">Y</span>`;
  if (handle === "system") return `<span class="avatar qwen ${cls || ""}" aria-hidden="true">✧</span>`;
  const k = sbAvatarClass(handle);
  const letter = k === "claude" ? "✳" : k === "codex" ? "◈" : (handle || "?")[0].toUpperCase();
  return `<span class="avatar ${k} ${cls || ""}" aria-hidden="true">${esc(letter)}</span>`;
}
function sbMark(size) { return `<img src="/icon.svg" width="${size}" height="${size}" alt="">`; }   // as the design uses its mark: an image the CSS sizes
/* our task states in the design's four: ready, building, review, done */
function sbStatus(t) {
  if (t.status === "done") return "done";
  if (["in_review", "proving"].includes(t.status)) return "review";
  if (["claimed", "changes_requested", "merge_blocked"].includes(t.status)) return "building";
  if (t.status === "cancelled") return "paused";
  return "ready";
}
function sbBadge(status, label) {
  return `<span class="status-badge ${status}"><i></i>${esc(label || { done: "Done", review: "In review", building: "Building", ready: "Up next", paused: "Paused" }[status] || status)}</span>`;
}
/* a seat in the design's words: reviewing, building, ready, paused */
function sbSeatState(x) {
  if (x.status === "paused" || S.project.frozen) return "paused";
  if (needsStart(x) || ["stuck", "limited"].includes((x.runner || {}).state)) return "reviewing";
  const lamp = lampOf(x);
  if (lamp === "busy") return (x.tasks || []).length ? "building" : "reviewing";
  return lamp === "on" ? "ready" : "paused";
}
function sbText(text) {
  return esc(plainText(text)).replace(/\b(T\d+)\b/g, '<a class="tid" href="#/task/$1">$1</a>').replace(/\b(Q\d+)\b/g, '<a class="tid" href="#/q/$1">$1</a>');
}
function sbTasks() { return S.tasks.filter(t => t.kind !== "epic" && !["cancelled", "backlog"].includes(t.status)); }

/* ---------------------------------------------------------------- the frame: sidebar, top bar, footer */

function sbSidebar(view) {
  const p = S.project;
  const tasks = sbTasks();
  const live = isLivePlan(S.plan);
  const reviews = S.tasks.filter(t => ["in_review", "proving", "changes_requested", "merge_blocked"].includes(t.status)).length;
  const asking = (S.councils || []).filter(c => !["done", "failed", "cancelled"].includes(c.stage)).length;
  const busy = S.seats.some(x => lampOf(x) === "busy");
  const nav = (v, ic, label, extra) => `<button data-view="${v}" class="nav-item${view === v ? " active" : ""}"${view === v ? ' aria-current="page"' : ""}>${pi(ic)}${label}${extra || ""}</button>`;
  return `<aside class="sidebar" id="sidebar" aria-label="Workspace navigation">
    <a class="brand" href="#/room" aria-label="Sabha home">${sbMark(43)}<span><strong>sabha<span class="brand-dot">.</span></strong><small>A SPACE FOR MANY MINDS</small></span></a>
    <button class="project-picker" data-go="#/switch" aria-label="Switch project" title="${esc(p.root)}"><span class="project-monogram">${esc((p.name || "?")[0].toUpperCase())}</span><span><strong id="project-name">${esc(p.name)}</strong><small>${esc(shortPath(p.root).split("/").slice(-2).join("/"))}</small></span><span class="picker-chevrons">⌃<br>⌄</span></button>
    <button class="search-button" data-action="search">${pi("search")}<span>Find anything</span><kbd>Ctrl K</kbd></button>
    <div class="nav-label">WORKSPACE</div>
    <nav class="main-nav" aria-label="Main views">
      ${nav("room", "room", "The room", busy ? '<span class="nav-live"></span>' : "")}
      ${nav("council", "council", "Ask the table", asking ? `<span class="nav-count">${asking}</span>` : "")}
      ${nav("plan", "plan", "Plan &amp; tasks", live && tasks.length ? `<span class="nav-count">${tasks.filter(t => t.plan === S.plan.id).length || tasks.length}</span>` : "")}
      ${nav("reviews", "review", "Reviews", reviews ? `<span class="nav-count warm">${reviews}</span>` : "")}
      ${nav("activity", "activity", "Activity")}
    </nav>
    <div class="nav-label team-label">AT THE TABLE <button data-go="#/add" aria-label="Add an AI to the table">+</button></div>
    <div class="sidebar-team" id="sidebar-team">${S.seats.map(x => {
      const st = sbSeatState(x);
      return `<button class="team-item" data-go="#/ai/${esc(x.handle)}" title="${esc(prettyModel(x.model))} · ${esc(seatPhrase(x))}">${sbAvatar(x.handle)}<span><strong>${esc(x.handle)}<small>${esc(sbApp(x.app))}</small></strong></span><span class="seat-dot ${st}" title="${esc(seatPhrase(x))}"></span></button>`;
    }).join("")}</div>
    <button class="new-room" data-go="#/switch">${pi("plus")}Set up a new room</button>
    <div class="sidebar-bottom">
      <button data-view="settings" class="nav-item${view === "settings" ? " active" : ""}">${pi("settings")}Settings<span class="shortcut">Ctrl ,</span></button>
      <button data-go="#/help" class="nav-item">${pi("help")}A little guidance<span class="external-arrow">↗</span></button>
      <div class="profile"><span class="profile-avatar">Y</span><span><strong>Your workspace</strong><small><span class="online-dot"></span>Everything stays local</small></span><button data-action="theme" aria-label="Change the colour theme">${pi(document.documentElement.dataset.theme === "dark" ? "sun" : "moon")}</button></div>
    </div>
    <div class="concept-label">SABHA ${esc(p.version || "")}</div>
  </aside>`;
}

function sbTopbar(view) {
  const [title, sub] = headline();
  const q = route.page === "q" && route.sub ? councilOf(route.sub.toUpperCase()) : null;
  const needs = (S.needs || []).filter(n => n.tone !== "info").length;
  return `<header class="topbar">
    <div class="breadcrumbs"><button class="mobile-menu icon-button" data-action="menu" aria-label="Toggle navigation" aria-controls="sidebar">${pi("menu")}</button><span class="breadcrumb-project">${esc(S.project.name)}</span><span class="slash">/</span><strong id="breadcrumb-view">${SB_NAME[view]}</strong>${q ? `<span class="slash">/</span><span class="breadcrumb-project">${esc(q.id)}</span>` : ""}</div>
    <div class="topbar-right"><span class="preview-badge" title="${esc(sub || "")}"><span></span>${esc(fit(q ? questionStatus(q) : title, 60))}</span><span class="topbar-divider"></span><button class="icon-button" data-go="#/inbox" aria-label="What needs you">${pi("bell")}${needs ? '<i class="notification-dot"></i>' : ""}</button><button class="profile-mini" data-go="#/help" aria-label="How Sabha works">Y</button></div>
  </header>`;
}

function sbFooter() {
  return `<footer class="app-footer"><span><span class="tiny-mark">✧</span> Thoughtfully together.</span><span>Your subscriptions <span>·</span> Your project <span>·</span> Nothing leaves this computer</span><button data-view="activity">Everything that happened <span>→</span></button></footer>`;
}

/* The whole page for a project; app.js's render() puts it in place and keeps typed text and scroll positions. */
function sabhaShell(freshDrawer) {
  SB_SLOTS = {};
  const view = sbView();
  const body = { room: sbRoom, council: sbCouncil, plan: sbPlan, reviews: sbReviews, activity: sbActivity, settings: sbSettings }[view]();
  const wrap = document.createElement("div");
  wrap.className = "sabha";
  wrap.innerHTML = sbSidebar(view) + `<div class="app-shell">${sbTopbar(view)}<main id="main" tabindex="-1">${body}</main>${sbFooter()}</div><div class="sidebar-scrim" data-action="menu"></div>`;
  fillSlots(wrap);
  if (DRAWERS.includes(route.page)) wrap.append(h("div", { class: "legacy" }, ...drawer(route.page, freshDrawer)));
  document.title = `${SB_NAME[view]} · ${S.project.name} · Sabha`;
  return wrap;
}

/* ---------------------------------------------------------------- the room */

function sbGoalBanner() {
  const p = S.plan;
  if (!p || !p.goal) return `<section class="goal-banner" aria-label="Current goal"><div class="goal-emblem">${pi("spark")}</div><div class="goal-copy"><span class="eyebrow">OUR SHARED DIRECTION</span><h2>Nothing yet. Give your AIs a goal.</h2><div class="goal-meta"><span>Write it in the box below: they plan it together, and nothing is built before you approve.</span></div></div></section>`;
  const tasks = sbTasks().filter(t => t.plan === p.id);
  const done = tasks.filter(t => t.status === "done").length;
  const steps = ["Plan", "Build", "Proof", "Review", "Merge"];
  let at = 0;
  if (p.stage === "done") at = 5;
  else if (p.stage === "locked") at = tasks.some(t => t.status === "in_review") ? 3 : tasks.some(t => t.status === "proving") ? 2 : tasks.length && done === tasks.length ? 4 : 1;
  const track = steps.map((s, i) => i < at ? `<span class="complete">${pi("check")}${s}</span>` : i === at ? `<span class="current">${S.project.frozen ? "Paused" : s}</span>` : `<span>${s}</span>`).join("<i></i>");
  return `<section class="goal-banner" aria-label="Current goal"><div class="goal-emblem">${pi(p.stage === "done" ? "check" : "spark")}</div><div class="goal-copy"><span class="eyebrow">${isLivePlan(p) ? "OUR SHARED DIRECTION" : "OUR LAST DIRECTION"}</span><h2>${esc(fit(plainText(p.goal), 150))}</h2><div class="goal-meta">${pi("git")}<span>${esc(S.project.main_branch || "main")}</span><span class="meta-dot">·</span><span>${tasks.length ? `${done} of ${tasks.length} tasks complete` : esc(p.stage_label)}</span></div></div><div class="goal-stage"><div class="stage-track">${track}</div><button class="text-button" data-view="plan">Open the plan ${pi("arrow")}</button></div></section>`;
}

function sbRoom() {
  const busy = S.seats.filter(x => lampOf(x) === "busy");
  const paused = S.project.frozen;
  const actions = S.seats.length ? `<span class="status-pill ${paused ? "muted" : busy.length ? "live" : "success"}"><i></i>${paused ? "Council paused" : busy.length ? "Council at work" : "Council resting"}</span>${sbBtn(paused ? "Resume" : "Pause", "pause", "quiet", paused ? "play" : "pause")}` : "";
  return `${sbHeading("A LITTLE MORE PERSPECTIVE", "The room", "Independent minds. One shared direction.", actions)}
    ${sbGoalBanner()}
    <div class="room-layout"><section class="conversation-panel"><div class="section-top"><div class="section-label">${pi("message")}Conversation<span class="quiet-count">${esc(dayLabel((allEvents().slice(-1)[0] || {}).day || "") || "Today")}</span></div><button class="icon-button" data-view="activity" aria-label="View all activity">${pi("more")}</button></div>
    <div class="conversation-feed" id="conversation-feed">${sbFeed()}</div>
    ${slot(() => asksView(), "legacy sb-asks")}
    ${sbComposer()}
    </section><aside class="context-column" aria-label="Council and project context">${sbCouncilCard()}${sbMiniPlan()}${sbMemoryCard()}</aside></div>`;
}

function sbFeed() {
  const events = allEvents();
  let out = "", day = "", group = null;
  const flush = () => {
    if (!group) return;
    const x = seatOf(group.actor);
    out += `<article class="message">${sbAvatar(group.actor)}<div class="message-content"><div class="message-meta"><strong>${esc(displayName(group.actor))}</strong>${x ? `<span>${esc(sbApp(x.app))}</span>` : ""}<time>${esc(group.at)}</time></div>${group.lines.join("")}</div></article>`;
    group = null;
  };
  if (events.length >= 80 && !cache.olderDone) out += `<div class="system-event"><span class="event-line"></span><button data-action="earlier">Show earlier messages</button></div>`;
  if (!events.length) out += `<div class="system-event"><span class="event-line"></span><span>${pi("spark")}Nothing yet. Write a goal or a question below.</span></div>`;
  events.forEach(e => {
    const m = say(e);
    if (!m) return;
    if (e.day !== day) { flush(); day = e.day; out += `<div class="conversation-date"><span></span>${esc(String(dayLabel(day)).toUpperCase())}<span></span></div>`; }
    if (m.council) { flush(); out += sbCouncilInline(m.council, e, m.text); return; }
    const actor = m.actor || e.actor;
    if (m.marker || (actor === "human" && (m.tone === "quiet" || /^(task|seat)\./.test(e.type)))) {
      flush();
      const text = (m.marker || (/^(Added|Removed) /.test(m.text) ? "You " + m.text[0].toLowerCase() + m.text.slice(1) : m.text)).replace(/\b1 tasks\b/g, "1 task");
      const ic = { plan: "plan", check: "check", review: "review", alert: "alert", x: "close", pause: "pause", play: "play", swap: "refresh" }[m.icon] || "council";
      out += `<div class="system-event${m.you ? " you" : ""}"><span class="event-line"></span><span>${pi(ic)}${sbText(text)}</span>${m.you ? `<button data-view="plan">Open the plan ${pi("chevron")}</button>` : `<time>${esc(e.at)}</time>`}</div>`;
      return;
    }
    if (actor === "human") {
      flush();
      out += `<article class="message user-message"><span class="avatar human">Y</span><div class="message-content"><div class="message-meta"><strong>You</strong><time>${esc(e.at)}</time></div><p>${sbText(m.text)}</p></div></article>`;
      return;
    }
    const line = `<p class="${m.tone || ""}">${m.tone === "good" ? pi("check", "line-icon good") : m.tone === "bad" ? pi("alert", "line-icon bad") : ""}${sbText(m.text)}</p>`;
    if (group && group.actor === actor && group.lines.length < 10) group.lines.push(line);
    else { flush(); group = { actor, at: e.at, lines: [line] }; }
  });
  flush();
  const working = S.seats.filter(x => lampOf(x) === "busy" && x.now && ago(x.now.t) < 300 && x.now.kind !== "start");
  if (S.project.frozen) out += `<div class="working-indicator">${pi("pause")}<span>The council is taking a breath.</span><span class="live-label">PAUSED</span></div>`;
  else working.slice(0, 3).forEach(x => {
    const [verb] = STEP[x.now.kind] || ["is working"];
    out += `<div class="working-indicator"><span class="thinking-dots"><i></i><i></i><i></i></span><span><strong>${esc(x.handle)}</strong> ${esc(verb)}: ${esc(fit(plainText(x.now.text), 120))}</span><span class="live-label">LIVE</span></div>`;
  });
  return out;
}

function sbCouncilInline(id, e, fallback) {
  const c = councilOf(id);
  const rescue = (c && c.kind === "rescue") || e.type === "council.rescue";
  const stage = c ? (c.stage === "done" ? "done" : ["failed", "cancelled"].includes(c.stage) ? "paused" : "building") : "ready";
  const label = c ? (c.stage === "done" ? "Answered" : c.stage === "failed" ? "Couldn't answer" : c.stage === "cancelled" ? "Stopped" : questionStatus(c)) : "";
  const q = c ? c.question : fallback || id;
  let out = rescue
    ? `<div class="system-event"><span class="event-line"></span><span>${pi("review")}A second opinion on ${esc(c && c.task || "a failing task")}</span><button data-go="#/q/${esc(id)}">Open ${pi("chevron")}</button></div>`
    : `<article class="message user-message"><span class="avatar human">Y</span><div class="message-content"><div class="message-meta"><strong>You</strong><span>Asked the table</span><time>${esc(e.at)}</time></div><p>${esc(fit(plainText(q), 400))}</p><button class="inline-task" data-go="#/q/${esc(id)}">${pi("council")}<span><b>${esc(id)}</b> ${esc(label)}</span>${sbBadge(stage, stage === "done" ? "Answered" : stage === "building" ? "Thinking" : label)}${pi("chevron")}</button></div></article>`;
  if (c && c.final && c.chair) out += `<article class="message">${sbAvatar(c.chair)}<div class="message-content"><div class="message-meta"><strong>${esc(c.chair)}</strong><span>${rescue ? "Diagnosis" : "The table's answer"}</span><time>${esc(e.at)}</time></div><p>${esc(fit(sbPlain(c.final), 420))}</p><button class="text-button" data-go="#/q/${esc(id)}">Read every answer ${pi("arrow")}</button></div></article>`;
  return out;
}

/* the message box: what it does depends on whether a plan is running */
function sbModes() {
  return isLivePlan(S.plan)
    ? [["note", "Tell them", "message", "Saved as a note every AI reads the next time it checks in."], ["ask", "Ask the table", "council", MODES.ask.tip],
      ["problem", "Report a problem", "alert", MODES.problem.hint], ["task", "Add a task", "plus", MODES.task.hint]]
    : [["plan", "Plan together", "plan", "Each AI writes a plan, they compare notes and agree on one. You approve it."], ["quick", "Just do it", "play", "One AI splits your message into tasks and they start."],
      ["ask", "Ask the table", "council", MODES.ask.tip]];
}
function sbMode() {
  const modes = sbModes().map(m => m[0]);
  const m = ui.compose === "goal" ? (ui.planMode === "quick" ? "quick" : "plan") : ui.compose;
  return modes.includes(m) ? m : modes[0];
}
function sbComposer() {
  if (!S.seats.length) return `<div class="review-callout"><span class="callout-icon">${pi("plus")}</span><span><strong>Bring your AIs to the table.</strong><small>Add two or more, from different companies, before giving them a goal.</small></span><button data-go="#/welcome">Add AIs ${pi("arrow")}</button></div>`;
  const mode = sbMode();
  const [, label, ic] = sbModes().find(m => m[0] === mode);
  const level = ui.level || S.project.review || "mid";
  const place = { plan: "A new idea, a goal, a little direction…", quick: "Tell them what to do, like “sol: fix the usage numbers”", ask: "Ask them anything. Each answers on its own first…",
    note: "Tell your AIs something they should know…", problem: "What's wrong? The first line is the title", task: "What needs doing?" }[mode];
  return `<form class="composer" id="composer"><label class="sr-only" for="message-input">Message your council</label><textarea id="message-input" data-k="sb-message-${mode}" rows="2" placeholder="${esc(place)}"></textarea><div class="composer-controls"><div class="composer-options"><button type="button" class="mode-picker" data-action="mode">${pi(ic)}<span>${label}</span>${pi("down")}</button>${["plan", "quick"].includes(mode) ? `<span class="composer-separator"></span><button type="button" class="depth-picker" data-action="depth">${pi("review")}<span>${{ low: "Light", mid: "Standard", high: "Thorough" }[level]}</span></button>` : ""}</div><button type="submit" class="send-button" aria-label="Send">${pi("up")}</button></div></form><div class="composer-footnote"><span>Your subscriptions. Your project. Your council.</span><span><kbd>Enter</kbd> to send <span>·</span> <kbd>Shift Enter</kbd> for a new line</span></div>`;
}

function sbCouncilCard() {
  const seats = S.seats;
  const orbit = seats.slice(0, 3).map((x, i) => `<button class="orbit-seat seat-${"abc"[i]}" data-go="#/ai/${esc(x.handle)}" aria-label="${esc(x.handle)}: ${esc(seatPhrase(x))}">${sbAvatar(x.handle)}<span>${esc(x.handle)}</span><i class="seat-dot ${sbSeatState(x)}"></i></button>`).join("");
  return `<section class="council-card"><div class="section-top"><span class="section-label">Around the table</span><button class="icon-button" data-go="#/add" aria-label="Add an AI">${pi("plus")}</button></div><div class="council-orbit"><svg class="orbit-connections" viewBox="0 0 280 240" aria-hidden="true"><circle cx="140" cy="117" r="78" fill="none" stroke="currentColor" stroke-dasharray="2 6"/><path d="M140 37v80M140 117 65 173M140 117l75 56" fill="none" stroke="currentColor"/></svg><div class="orbit-core">${sbMark(40)}<span>Shared<br>context</span></div>${orbit}</div><div class="seat-status-list">${seats.map(x => `<button data-go="#/ai/${esc(x.handle)}"><span class="seat-dot ${sbSeatState(x)}"></span><strong>${esc(x.handle)}</strong><span>${esc(fit(seatPhrase(x), 34))}</span>${pi("chevron")}</button>`).join("")}</div><div class="council-card-footer"><span class="online-dot"></span>${seats.length > 1 ? `${seats.length} independent minds, connected.` : "Add a second AI for a real council."}</div></section>`;
}

function sbMiniPlan() {
  const p = S.plan;
  const tasks = sbTasks().filter(t => !p || t.plan === p.id);
  const done = tasks.filter(t => t.status === "done").length;
  return `<section class="mini-plan"><div class="section-top"><span class="section-label">A little progress</span><span class="fraction">${done}<span> / ${tasks.length}</span></span></div><div class="mini-progress"><span style="width:${tasks.length ? done / tasks.length * 100 : 0}%"></span></div>${tasks.slice(0, 7).map(t => {
    const st = sbStatus(t);
    return `<button class="mini-task" data-go="#/task/${esc(t.id)}"><span class="task-mark ${st}">${st === "done" ? pi("check") : st === "building" ? "<i></i>" : ""}</span><span>${esc(t.title)}</span></button>`;
  }).join("") || '<p class="body-muted">No tasks yet. They appear when a plan is approved.</p>'}<button class="text-button" data-view="plan">See the whole picture ${pi("arrow")}</button></section>`;
}

function sbMemoryCard() {
  const notes = S.memories || [];
  const last = notes.length ? notes[notes.length - 1] : null;
  return `<button class="memory-card" data-go="#/notes"><span class="eyebrow">${pi("book")}SHARED CONTEXT</span><p>${esc(last ? fit(plainText(last.text || last.l1 || last.summary || ""), 180) : "Nothing shared yet. A note you send reaches every AI the next time it checks in.")}</p><span>Held in common ${pi("external")}</span></button>`;
}

/* ---------------------------------------------------------------- ask the table */

function sbCouncil() {
  const all = S.councils || [];
  const id = route.page === "q" && route.sub ? route.sub.toUpperCase() : all.length ? all[0].id : "";
  const d = id ? cache.council[id] : null;
  if (id && !d) loadCouncil(id).then(render);
  const askers = (S.can_ask || []).filter(hd => !ui.askSkip[hd]);
  const people = (S.can_ask || []).map(hd => `<button type="button" class="asker${ui.askSkip[hd] ? " skipped" : ""}" data-action="toggle-asker" data-id="${esc(hd)}" title="${esc(hd)}${ui.askSkip[hd] ? " (not answering)" : ""}">${sbAvatar(hd)}</button>`).join("");
  const follow = ui.followUp ? `<span class="follow-chip">${pi("message")}Following up on ${esc(ui.followUp)}<button type="button" data-action="no-follow" aria-label="Not a follow-up">${pi("x")}</button></span>` : "";
  const composer = `<form class="question-composer" id="question-form"><div class="eyebrow">WHAT’S ON YOUR MIND?</div><label class="sr-only" for="council-input">Your question to the table</label><textarea id="council-input" data-k="sb-ask" rows="2" placeholder="What would you like a second perspective on?"></textarea><div class="question-composer-footer"><span class="question-people">${people}<span>${askers.length ? `${askers.length} perspective${askers.length > 1 ? "s" : ""}` : "Nobody can answer yet"}</span>${follow}</span><button class="btn primary" type="submit">Ask the table ${pi("arrow")}</button></div></form>`;
  const earlier = all.filter(c => c.id !== id).slice(0, 6);
  const aside = `<aside class="council-explainer"><span class="eyebrow">THE BEAUTY OF THE PROCESS</span><h2>A little disagreement.<br>A better answer.</h2><p>Every model answers before seeing the others. They review and rank anonymous answers, then the strongest perspective brings it all together.</p><div class="principle">${pi("lock")}<span><strong>Independent first</strong><small>No model sets the direction for the others.</small></span></div><div class="principle">${pi("review")}<span><strong>Reviewed without names</strong><small>Ideas are judged on their merit.</small></span></div><div class="principle">${pi("council")}<span><strong>Considered together</strong><small>A final answer carries the best of every view.</small></span></div>${earlier.length ? `<div class="earlier-questions"><span class="eyebrow">EARLIER QUESTIONS</span>${earlier.map(c => `<button class="mini-task" data-go="#/q/${esc(c.id)}"><span class="task-mark ${c.stage === "done" ? "done" : c.stage === "failed" || c.stage === "cancelled" ? "paused" : "building"}">${c.stage === "done" ? pi("check") : ""}</span><span>${esc(c.kind === "rescue" ? "Second opinion on " + c.task : fit(plainText(c.question).split("\n")[0], 70))}</span></button>`).join("")}</div>` : ""}<div class="sample-note">${pi("help")}They can read your project, but change nothing.</div></aside>`;
  return `${sbHeading("GOOD QUESTIONS DESERVE GOOD COMPANY", "Ask the table", "Let each mind think independently. Then find the strongest answer.", sbBtn("New question", "new-question", "secondary", "plus"))}
    <div class="council-page-grid"><div class="council-main">${composer}${id ? sbAnswerCard(id, d) : `<section class="answer-card"><div class="thinking-state">${sbMark(64)}<h3>No questions yet.</h3><p>Ask one above: every AI answers on its own, they rank each other's answers without names, and the best one writes the final answer.</p></div></section>`}</div>${aside}</div>`;
}

function sbAnswerCard(id, d) {
  if (!d) return `<section class="answer-card"><div class="thinking-state">${sbMark(64)}<h3>Loading ${esc(id)}…</h3></div></section>`;
  if (d.ok === false) return `<section class="answer-card"><div class="thinking-state"><h3>There is no question ${esc(id)}.</h3></div></section>`;
  const rescue = d.kind === "rescue";
  const finished = ["done", "failed", "cancelled"].includes(d.stage);
  const at = { answering: 0, ranking: 1, combining: 2, done: 3 }[d.stage] ?? 3;
  const answers = d.parts.filter(x => x.stage === "answer");
  const ranks = d.parts.filter(x => x.stage === "rank");
  const tab = ui.ctab[id] || "synthesis";
  const stageText = { answering: "Thinking independently", ranking: "Ranking anonymously", combining: "Bringing it together", done: "A considered answer", failed: "Couldn't answer", cancelled: "Stopped" }[d.stage] || d.stage;
  const process = ["Independent answers", "Blind peer ranking", "Final synthesis"].map((name, i) => `<span class="${at > i ? "complete" : at === i && !finished ? "current" : ""}"><i>${at > i ? pi("check") : i + 1}</i>${name}</span>`).join("<b></b>");
  const tabs = ["synthesis", "answers", "rankings"].map(t => `<button role="tab" aria-selected="${tab === t}" class="${tab === t ? "active" : ""}" data-action="council-tab" data-tab="${t}" data-id="${esc(id)}">${{ synthesis: rescue ? "Diagnosis" : "Synthesis", answers: "Independent answers", rankings: "Peer rankings" }[t]}${t === "answers" ? `<span>${answers.length}</span>` : ""}</button>`).join("");
  const placeOf = seat => { const i = (d.ranking || []).findIndex(r => r.seat === seat); return i < 0 ? 0 : i + 1; };
  let panel;
  if (tab === "answers") {
    panel = `<div class="independent-answers">${answers.map(a => {
      const place = (d.ranking || []).length > 1 ? placeOf(a.seat) : 0;
      return `<article class="independent-answer"><div class="answer-label"><span>${rescue ? esc(a.seat).toUpperCase() : "ANSWER " + esc(a.label || "?")}</span><small>${esc(a.seat)} · ${esc(prettyModel((seatOf(a.seat) || {}).model || ""))}${place ? " · ranked #" + place : ""}${a.tokens ? " · " + num(a.tokens) + " tokens" : ""}</small></div>${a.status === "running" ? `<p class="body-muted">Writing its answer <span class="thinking-dots"><i></i><i></i><i></i></span></p>` : a.error ? `<p class="body-muted">Couldn't answer: ${esc(plainText(a.error))}</p>` : mdSlot(a.text)}</article>`;
    }).join("")}</div>`;
  } else if (tab === "rankings") {
    const labelSeat = Object.fromEntries(answers.map(a => [a.label, a.seat]));
    panel = (d.ranking || []).length > 1 ? `<div class="rankings"><p class="body-muted">Each model ranked the answers without seeing who wrote them, its own included.</p><div class="ranking-table"><div class="ranking-row ranking-header"><span>ANSWER</span><span>FIRST-PLACE VOTES</span><span>COUNCIL RANK</span></div>${d.ranking.map((r, i) => `<div class="ranking-row"><strong>Answer ${esc(r.label)} · ${esc(r.seat)}</strong><span>${r.firsts || 0} of ${ranks.length}</span><span class="rank-number ${i === 0 ? "winner" : ""}">${i === 0 ? pi("check") : ""}#${i + 1}</span></div>`).join("")}</div><div class="insight-note">${pi("spark")}${esc(ranks.map(r => `${r.seat} ranked ${(r.ranking || []).map(l => labelSeat[l] || l).join(" > ") || "nothing yet"}`).join(" · "))}</div>${ranks.map(r => r.text ? `<article class="independent-answer"><div class="answer-label"><span>WHY ${esc(r.seat).toUpperCase()} RANKED THEM SO</span><small>written without knowing who wrote which</small></div>${mdSlot(String(r.text).split("FINAL RANKING:")[0])}</article>` : "").join("")}</div>`
      : `<div class="thinking-state"><h3>${finished ? "Only one answer, so nothing to rank." : "The rankings appear once every answer is in."}</h3></div>`;
  } else if (!d.final && !finished) {
    panel = `<div class="thinking-state">${sbMark(64)}<h3>${esc(stageText)}.</h3><p>Each perspective gets space before the council compares notes.</p><span class="thinking-dots"><i></i><i></i><i></i></span></div>`;
  } else if (!d.final) {
    panel = `<div class="thinking-state"><h3>${esc(stageText)}.</h3><p>${esc(plainText(d.error || ""))}</p></div>`;
  } else {
    const by = d.chair ? `Brought together by ${esc(d.chair)}${(d.ranking || []).length > 1 && placeOf(d.chair) === 1 ? ", whose answer the others ranked best" : ""} · reviewed by the council` : "";
    panel = `<div class="synthesis"><div class="synthesis-by">${sbAvatar(d.chair || "system")}<span><strong>${rescue ? "A diagnosis" : "A considered answer"}</strong><small>${by}</small></span><span class="small-badge">${num(d.tokens)} TOKENS</span></div>${mdSlot(d.final)}<div class="synthesis-footer">${rescue ? "" : `<button class="btn primary" data-action="build-answer" data-id="${esc(id)}">Build this ${pi("arrow")}</button><button class="btn quiet" data-action="follow-up" data-id="${esc(id)}">${pi("message")}Ask a follow-up</button>`}<button class="icon-button copy-answer" data-action="copy-answer" data-id="${esc(id)}" aria-label="Copy the answer">${pi("copy")}</button></div></div>`;
  }
  return `<section class="answer-card"><div class="council-process">${process}</div><div class="answer-heading"><span class="eyebrow">QUESTION ${esc(id.replace(/^Q/, "").padStart(2, "0"))}</span><span class="status-pill ${finished ? (d.stage === "done" ? "success" : "muted") : "live"}"><i></i>${esc(stageText)}</span></div><h2>${esc(rescue ? "Second opinion on " + d.task : fit(plainText(d.question), 300))}</h2><div class="tabs" role="tablist" aria-label="Council answer views">${tabs}</div><div id="council-panel" role="tabpanel">${panel}</div>${finished ? "" : `<div class="synthesis-footer">${sbBtn("Stop it", "stop-question", "quiet", "x", `data-id="${esc(id)}"`)}</div>`}</section>`;
}

/* ---------------------------------------------------------------- plan & tasks */

function sbPlan() {
  const p = S.plan;
  const live = isLivePlan(p);
  const head = sbHeading("FROM AN IDEA TO SOMETHING REAL", "A shared direction", "A clear plan. Independent ownership. Work you can verify.", live ? sbBtn("Plan details", "plan-details", "secondary", "book") : sbBtn("New goal", "new-goal", "primary", "plus"));
  if (!p) return head + `<section class="plan-overview"><div class="plan-overview-top"><div><span class="eyebrow">CURRENT GOAL</span><h2>No shared direction yet.</h2></div></div><div class="plan-agreement"><span>Give your AIs a goal: they each write a plan without seeing the others', comment on each other's, and agree on one for you to approve.</span>${sbBtn("New goal", "new-goal", "primary", "plus")}</div></section>`;
  const order = ["drafting", "critique", "merging", "proposed", "awaiting_human", "locked"];
  const at = p.stage === "done" ? 6 : p.stage === "voting" ? 3 : Math.max(0, order.indexOf(p.stage));
  const labels = p.mode === "quick" ? ["Your message", "Split into tasks", "Combined plan", "Team agreement", "Your approval", "Build together"]
    : ["Independent drafts", "Anonymous critique", "Combined plan", "Team agreement", "Your approval", "Build together"];
  const pipeline = labels.map((label, i) => `<div class="pipeline-step ${i < at ? "complete" : i === at ? "current" : ""}"><span>${i < at ? pi("check") : String(i + 1).padStart(2, "0")}</span><strong>${label}</strong></div>`).join("");
  const waiting = p.stage === "awaiting_human";
  const pill = p.stage === "done" ? ["success", "Done"] : p.stage === "locked" ? ["success", "Plan agreed & locked"] : waiting ? ["attention", "Waiting for your approval"] : p.stage === "cancelled" ? ["muted", "Cancelled"] : ["live", p.stage_label];
  const people = (p.people || []).map(x => sbAvatar(x.seat, "small")).join("");
  const agree = waiting ? `<button class="btn primary" data-action="approve-plan" ${ui.approvalReady ? "" : "disabled"}>Approve plan &amp; begin ${pi("arrow")}</button>` : `<button class="text-button" data-action="plan-details">Read the reasoning ${pi("arrow")}</button>`;
  const approval = waiting ? `<section class="plan-approval"><div><span class="eyebrow">PROOF BEFORE COMPLETION</span><h3>Agree on what “done” means.</h3><p class="body-muted">Each owner runs its task's test command before the work can move to review. These commands run on your computer.</p></div><div class="plan-command-list">${(p.tasks || []).map(t => `<div><strong>${esc(t.ref)}</strong><code>${esc((t.proof || []).join(" && ") || "no test command")}</code></div>`).join("")}</div><label class="approval-confirm"><input id="approval-confirm" type="checkbox" ${ui.approvalReady ? "checked" : ""}>I’ve reviewed the file scope and test commands.</label></section>` : "";
  const tasks = sbTasks().filter(t => t.plan === p.id);
  return head + `<section class="plan-overview"><div class="plan-overview-top"><div><span class="eyebrow">CURRENT GOAL</span><h2>${esc(fit(plainText(p.goal), 220))}</h2></div><span class="status-pill ${pill[0]}"><i></i>${esc(pill[1])}</span></div><div class="plan-pipeline">${pipeline}</div><div class="plan-agreement"><div class="avatar-stack">${people}</div><span>${esc(stageNote(p, p.stage) || "Different perspectives, an agreed plan.")}</span>${agree}</div></section>${approval}
    <div class="tasks-heading"><div><h2>The work ahead<span class="quiet-count">${tasks.length}</span></h2><p>Each task has one owner, its own files, and a clear proof.</p></div><div class="view-switch" role="group" aria-label="Task layout"><button data-action="task-layout" data-layout="list" class="${ui.tlayout !== "board" ? "active" : ""}" aria-label="List view">${pi("list")}</button><button data-action="task-layout" data-layout="board" class="${ui.tlayout === "board" ? "active" : ""}" aria-label="Board view">${pi("grid")}</button></div></div>
    <div class="task-toolbar"><div class="filter-pills" role="group" aria-label="Filter tasks">${[["all", "All tasks"], ["building", "Building"], ["review", "In review"], ["done", "Done"]].map(([s, label]) => `<button class="${(ui.tfilter || "all") === s ? "active" : ""}" data-action="task-filter" data-filter="${s}">${label}</button>`).join("")}</div><label class="inline-search">${pi("search")}<input id="task-search" data-k="sb-task-search" type="search" placeholder="Find a task…" aria-label="Search tasks"></label></div>
    <div id="task-list">${sbTaskList(tasks)}</div><div class="proof-note">${pi("review")}Done means the test passed, the review cleared, and the work merged. Each is shown separately.</div>`;
}

function sbTaskList(tasks) {
  const f = ui.tfilter || "all", q = (ui.tsearch || "").toLowerCase();
  const list = tasks.filter(t => (f === "all" || sbStatus(t) === f) && `${t.id} ${t.title} ${t.owner || ""}`.toLowerCase().includes(q));
  if (!list.length) return `<div class="empty-state">${pi("search")}<h3>${tasks.length ? "No tasks match that." : "No tasks yet."}</h3><p>${tasks.length ? "Try another word or choose a different status." : "They appear here when the plan is agreed."}</p></div>`;
  const owner = t => t.owner ? `${sbAvatar(t.owner, "small")}${esc(t.owner)}` : '<span class="body-muted">Nobody yet</span>';
  if (ui.tlayout === "board") return `<div class="task-board">${[["ready", "Up next"], ["building", "In motion"], ["review", "In review"], ["done", "Complete"]].map(([st, title]) => {
    const col = list.filter(t => sbStatus(t) === st);
    return `<section class="board-column"><div class="board-column-title"><span class="seat-dot ${st}"></span><h3>${title}</h3><span>${col.length}</span></div>${col.map(t => `<button class="task-card" data-go="#/task/${esc(t.id)}"><div class="task-card-top"><span class="task-id">${esc(t.id)}</span>${sbBadge(sbStatus(t), t.status_label)}</div><h3>${esc(t.title)}</h3><p>${esc(fit(plainText(t.summary || ""), 140))}</p><div class="task-card-bottom">${owner(t)}<span class="file-count">${pi("file")}${(t.files || []).length} files</span></div>${(t.waits_for || []).length ? `<div class="dependency-label">${pi("git")}After ${esc(t.waits_for.join(", "))}</div>` : ""}</button>`).join("") || '<div class="empty-column">A little breathing room.</div>'}</section>`;
  }).join("")}</div>`;
  return `<div class="task-table"><div class="task-table-head"><span>TASK</span><span>OWNER</span><span>STATUS</span><span></span></div>${list.map(t => {
    const st = sbStatus(t);
    return `<button class="task-row" data-go="#/task/${esc(t.id)}"><span class="task-row-title"><span class="task-mark ${st}">${st === "done" ? pi("check") : ""}</span><span><strong><span class="task-id">${esc(t.id)}</span>${esc(t.title)}</strong><small>${(t.files || []).length} scoped files${(t.waits_for || []).length ? " · Depends on " + esc(t.waits_for.join(", ")) : ""}${t.proof_status ? " · tests " + esc(t.proof_status) : ""}</small></span></span><span class="task-owner">${owner(t)}</span>${sbBadge(st, t.status_label)}${pi("chevron")}</button>`;
  }).join("")}</div>`;
}

/* ---------------------------------------------------------------- reviews */

function sbReviews() {
  const open = S.tasks.filter(t => ["in_review", "proving", "changes_requested", "merge_blocked"].includes(t.status));
  const merged = S.tasks.filter(t => t.status === "done").slice(-6).reverse();
  const yours = open.filter(t => t.status === "merge_blocked" || (S.reviews || []).some(r => r.task === t.id && r.reviewer === "human"));
  const pill = open.length ? `<span class="status-pill attention"><i></i>${open.length} being checked</span>` : `<span class="status-pill success"><i></i>Nothing waiting</span>`;
  const row = t => `<button class="task-row" data-go="#/review/${esc(t.id)}"><span class="task-row-title"><span class="task-mark ${sbStatus(t)}">${t.status === "done" ? pi("check") : ""}</span><span><strong><span class="task-id">${esc(t.id)}</span>${esc(t.title)}</strong><small>${esc(taskStatus(t))}${t.proof_status ? " · tests " + esc(t.proof_status) : ""}</small></span></span><span class="task-owner">${t.owner ? sbAvatar(t.owner, "small") + esc(t.owner) : ""}</span>${sbBadge(sbStatus(t), t.status_label)}${pi("chevron")}</button>`;
  return `${sbHeading("TRUST, WITH SOMETHING TO SHOW FOR IT", "A considered review", "A second perspective, passing tests, and your final say.", pill)}
    <div class="review-layout"><section class="review-main">${open.length ? `<div class="review-title"><span class="eyebrow">BEING CHECKED NOW</span><h2>${open.length === 1 ? esc(open[0].title) : `${open.length} pieces of work`}</h2></div><div class="task-table">${open.map(row).join("")}</div>`
      : `<div class="empty-state">${pi("review")}<h3>Nothing waits for review.</h3><p>When an AI finishes a task, its tests run and an AI from another company checks the change. It shows up here.</p></div>`}
      ${merged.length ? `<div class="review-summary"><h3>Recently merged</h3><div class="task-table">${merged.map(t => `<button class="task-row" data-go="#/task/${esc(t.id)}"><span class="task-row-title"><span class="task-mark done">${pi("check")}</span><span><strong><span class="task-id">${esc(t.id)}</span>${esc(t.title)}</strong><small>${esc(t.updated || "")}</small></span></span><span class="task-owner">${t.owner ? sbAvatar(t.owner, "small") + esc(t.owner) : ""}</span>${sbBadge("done")}${pi("chevron")}</button>`).join("")}</div></div>` : ""}</section>
    <aside class="review-checks"><h3>Confidence, step by step.</h3><div class="check-row"><span class="check-circle">${pi("terminal")}</span><div><strong>Proof</strong><small>The task's own test command, run by Sabha, not by the AI.</small></div></div><div class="check-row"><span class="check-circle">${pi("review")}</span><div><strong>Independent review</strong><small>An AI from a different company reads the change.</small></div></div><div class="check-row"><span class="check-circle ${yours.length ? "pending" : ""}">${pi(yours.length ? "clock" : "check")}</span><div><strong>${yours.length ? `${yours.length} need${yours.length > 1 ? "" : "s"} you` : "Your say"}</strong><small>${yours.length ? "Open it to decide." : "Big or risky changes come to you before they merge."}</small></div></div><div class="leased-files"><span class="eyebrow">FILE OWNERSHIP</span><p>${pi("lock")}While an AI works on a task, its files are its alone. Others can read and review them.</p></div></aside></div>`;
}

/* ---------------------------------------------------------------- activity */

const SB_KIND = e => /^council\./.test(e.type) ? "decisions" : /^review\.|proof|merge/.test(e.type) ? "reviews" : /^(plan|human|vote|alert)\./.test(e.type) ? "decisions" : "building";
const SB_EICON = e => /^council\./.test(e.type) ? "council" : /^review\./.test(e.type) ? "review" : /proof/.test(e.type) ? "terminal" : e.type === "task.done" ? "git" : /^plan\./.test(e.type) ? "plan" : /^seat\./.test(e.type) ? "council" : /^alert\./.test(e.type) ? "alert" : "file";
function sbActivity() {
  const events = allEvents().slice().reverse();
  const f = ui.afilter || "all", q = (ui.asearch || "").toLowerCase();
  const rows = [];
  for (const e of events) {
    const m = say(e);
    if (!m) continue;
    if (f !== "all" && SB_KIND(e) !== f) continue;
    const title = plainText(m.marker || m.text || (m.council ? "Asked the table" : e.text));
    if (q && !`${title} ${e.text} ${e.actor}`.toLowerCase().includes(q)) continue;
    rows.push(`<article class="timeline-event"><span class="timeline-icon ${SB_KIND(e)}">${pi(SB_EICON(e))}</span><div><div class="timeline-title"><strong>${sbText(fit(title, 160))}</strong><time>${esc(e.day)} · ${esc(e.at)}</time></div><p>${esc(e.type.replace(".", " · ").replace(/_/g, " "))}${e.task ? " · " + esc(e.task) : ""}</p><span class="timeline-actor">${sbAvatar(e.actor === "human" ? "human" : e.actor, "small")}${esc(displayName(e.actor))}</span></div></article>`);
    if (rows.length >= 150) break;
  }
  const tasks = sbTasks();
  const checks = allEvents().filter(e => e.type === "task.proof_passed").length;
  return `${sbHeading("EVERY STEP, IN THE OPEN", "The work, unfolding", "A quiet record of what happened, who did it, and what it proved.", sbBtn("Export activity", "export-activity", "secondary", "external") + sbBtn("Search older", "search-older", "quiet", "search"))}
    <div class="activity-summary"><div><strong>${tasks.filter(t => t.status === "done").length}<span>/${tasks.length}</span></strong><span>Tasks complete</span></div><div><strong>${checks}</strong><span>Passing checks</span></div><div><strong>${S.seats.length}</strong><span>Independent perspectives</span></div><div><strong>${(S.councils || []).length}</strong><span>Recent questions</span></div></div>
    <div class="activity-panel"><div class="activity-toolbar"><div class="filter-pills" role="group" aria-label="Filter activity">${[["all", "Everything"], ["building", "Building"], ["reviews", "Reviews"], ["decisions", "Decisions"]].map(([k, t]) => `<button data-action="activity-filter" data-filter="${k}" class="${f === k ? "active" : ""}">${t}</button>`).join("")}</div><label class="inline-search">${pi("search")}<input id="activity-search" data-k="sb-activity-search" type="search" placeholder="Find in this list…" aria-label="Search activity"></label></div><div class="activity-timeline">${rows.join("") || '<div class="empty-state">No activity in this view yet.</div>'}</div></div>`;
}

/* ---------------------------------------------------------------- settings */

function sbSettings() {
  const theme = themeName();
  const level = S.project.review || "mid";
  const opt = (key, label, sub, mini) => `<button data-action="set-theme" data-theme="${key}" class="theme-option ${theme === key ? "selected" : ""}" aria-pressed="${theme === key}"><span class="theme-miniature ${mini}"><i></i><span><b></b><b></b><b></b></span></span><span class="theme-description"><strong>${label}</strong><small>${sub}</small></span><span class="radio-mark">${theme === key ? pi("check") : ""}</span></button>`;
  const usage = S.seats.map(x => {
    const snap = (x.usage || {}).snapshot;
    const pct = snap && snap.session_pct != null ? Math.round(snap.session_pct) : snap && snap.pct != null ? Math.round(snap.pct) : null;
    const ex = (x.usage || {}).exchange || {};
    return `<button class="usage-card" data-go="#/ai/${esc(x.handle)}"><span class="usage-person">${sbAvatar(x.handle)}<span><strong>${esc(x.handle)}</strong><small>${esc(sbApp(x.app))}</small></span></span><div class="usage-reading"><strong>${pct == null ? (ex.tokens_today ? num(ex.tokens_today) : "—") : pct + "%"}</strong><span>${pct == null ? (ex.tokens_today ? "tokens with Sabha today" : esc(fit((x.usage || {}).text || "Not reported by this app", 60))) : "of current session limit"}</span></div><span class="usage-meter"><i style="width:${pct || 0}%"></i></span><span class="usage-caption">${(x.runner || {}).state === "limited" ? "Out of usage until " + esc(hm(x.runner.limited_until)) : "Open for the details"}</span></button>`;
  }).join("");
  const conns = S.seats.map(x => `<div class="connection-row">${sbAvatar(x.handle)}<span><strong>${esc(sbApp(x.app))}</strong><small>${esc(x.handle)} · ${esc(prettyModel(x.model))}${x.effort ? " · " + esc(EFFORT_LABEL[x.effort] || x.effort) + " thinking" : ""}</small></span><span class="connection-status"><i class="online-dot"></i>${esc(fit(seatPhrase(x), 30))}</span><button class="text-button" data-go="#/ai/${esc(x.handle)}">Manage ${pi("arrow")}</button></div>`).join("");
  return `${sbHeading("MAKE A LITTLE ROOM FOR YOURSELF", "Your kind of workspace", "Set the atmosphere. Choose how your council works.", sbBtn("Open another project", "open-project", "secondary", "folder"))}<div class="settings-layout"><nav class="settings-nav" aria-label="Settings sections"><a href="#appearance" data-action="settings-anchor" data-anchor="appearance" class="active">${pi("sun")}Appearance</a><a href="#collaboration" data-action="settings-anchor" data-anchor="collaboration">${pi("council")}Collaboration</a><a href="#usage" data-action="settings-anchor" data-anchor="usage">${pi("activity")}Subscription usage</a><a href="#connections" data-action="settings-anchor" data-anchor="connections">${pi("terminal")}Your connections</a><a href="#everything" data-action="settings-anchor" data-anchor="everything">${pi("settings")}Everything else</a></nav><div class="settings-sections">
    <section class="settings-section" id="appearance"><div class="section-heading"><span class="eyebrow">01 / ATMOSPHERE</span><h2>A space that feels right.</h2><p>Quiet by design. Comfortable at any hour.</p></div><div class="theme-options">${opt("light", "Paper", "Warm ivory, ink, and a little saffron.", "light")}${opt("dark", "After hours", "Deep indigo with a softer glow.", "dark")}${opt("auto", "Follow the system", "Paper by day, After hours by night.", "light")}</div></section>
    <section class="settings-section" id="collaboration"><div class="section-heading"><span class="eyebrow">02 / COLLABORATION</span><h2>How carefully should we look?</h2><p>Choose a review depth that suits the work. It applies to new plans.</p></div><div class="depth-options">${[["low", "Light", "Tests are the gate. A quick path for familiar work.", "leaf"], ["mid", "Standard", "Independent review from another model family.", "review"], ["high", "Thorough", "Full diff review, with every concern addressed.", "council"]].map(([key, label, sub, ic]) => `<button data-action="set-depth" data-depth="${key}" class="depth-option ${level === key ? "selected" : ""}" aria-pressed="${level === key}"><span>${pi(ic)}<strong>${label}</strong>${key === "mid" ? "<small>RECOMMENDED</small>" : ""}</span><p>${sub}</p><span class="radio-mark">${level === key ? pi("check") : ""}</span></button>`).join("")}</div></section>
    <section class="settings-section" id="usage"><div class="section-heading"><span class="eyebrow">03 / A LITTLE AWARENESS</span><h2>Your plans, at a glance.</h2><p>The subscriptions you already have, as each app reports them.</p></div><div class="usage-cards">${usage || '<p class="body-muted">No AIs yet.</p>'}</div></section>
    <section class="settings-section" id="connections"><div class="section-heading"><span class="eyebrow">04 / YOUR OWN TOOLS</span><h2>Bring your familiar minds.</h2><p>Claude Code, Codex, opencode, and other MCP-compatible apps.</p></div>${conns}<button class="btn secondary" data-go="#/add">${pi("plus")}Bring another mind</button></section>
    <section class="settings-section" id="everything"><div class="section-heading"><span class="eyebrow">05 / EVERYTHING ELSE</span><h2>The fine print.</h2><p>Every setting, in plain words.</p></div>${slot(() => (PAGES.settings(S) || {}).body, "legacy sb-legacy-block")}</section>
  </div></div>`;
}

/* ---------------------------------------------------------------- dialogs (the design's own modal) */

const SB_MODAL = () => document.getElementById("modal");
function sbModalHead(title, sub) {
  return `<header class="dialog-header"><div><div class="eyebrow">YOUR WORKSPACE</div><h2 id="modal-title">${esc(title)}</h2>${sub ? `<p>${esc(sub)}</p>` : ""}</div><button class="icon-button" data-action="close-modal" aria-label="Close dialog">${pi("close")}</button></header>`;
}
function sbShowModal(html, cls) {
  const d = SB_MODAL();
  if (!d) return;
  if (d.open) d.close();
  d.className = "modal " + (cls || "");
  d.innerHTML = html;
  d.showModal();
  const f = d.querySelector("textarea, input");
  if (f) f.focus();
}
function sbCloseModal() { const d = SB_MODAL(); if (d && d.open) d.close(); }

function sbPalette() {
  const routes = [["room", "The room", "Your shared conversation"], ["council", "Ask the table", "Get independent perspectives"], ["plan", "Plan & tasks", "See the work ahead"],
    ["reviews", "Reviews", "What is being checked"], ["activity", "Activity", "Follow the work"], ["settings", "Settings", "Make the workspace your own"]];
  const ic = v => ({ council: "council", reviews: "review", settings: "settings", activity: "activity", plan: "plan" }[v] || "room");
  sbShowModal(`<div class="command-search"><h2 id="modal-title" class="sr-only">Find anything in your workspace</h2>${pi("search")}<input id="command-input" type="search" placeholder="Where would you like to go?" aria-label="Search the workspace"><button data-action="close-modal"><kbd>ESC</kbd></button></div><div class="command-results" id="command-results">${routes.map(([v, t, d]) => `<button data-view="${v}" data-search-text="${t.toLowerCase()}">${pi(ic(v))}<span><strong>${t}</strong><small>${d}</small></span>${pi("arrow")}</button>`).join("")}${S.seats.map(x => `<button data-go="#/ai/${esc(x.handle)}" data-search-text="${esc((x.handle + " " + x.model).toLowerCase())}">${sbAvatar(x.handle, "small")}<span><strong>${esc(x.handle)}</strong><small>${esc(prettyModel(x.model))} · ${esc(seatPhrase(x))}</small></span>${pi("arrow")}</button>`).join("")}${sbTasks().slice(-40).reverse().map(t => `<button data-go="#/task/${esc(t.id)}" data-search-text="${esc((t.id + " " + t.title).toLowerCase())}">${pi("file")}<span><strong>${esc(t.id)} · ${esc(t.title)}</strong><small>${esc(t.status_label)}</small></span>${pi("arrow")}</button>`).join("")}${(S.councils || []).map(c => `<button data-go="#/q/${esc(c.id)}" data-search-text="${esc((c.id + " " + c.question).toLowerCase())}">${pi("council")}<span><strong>${esc(c.id)} · ${esc(fit(plainText(c.question), 70))}</strong><small>A question to the table</small></span>${pi("arrow")}</button>`).join("")}</div><div class="command-footnote">A little shortcut to the whole workspace. Older history: Activity → Search older.</div>`, "command-modal");
}

/* ---------------------------------------------------------------- sending */

async function sbSend(text, mode, btn) {
  text = (text || "").trim();
  const level = ui.level || S.project.review || "mid";
  const clear = () => { const el = document.getElementById(mode === "ask-page" ? "council-input" : "message-input"); if (el) el.value = ""; };
  if (!text) { toast(mode === "ask" || mode === "ask-page" ? "Write your question first" : "Write something first", "One or two sentences is enough."); return; }
  const first = text.split("\n")[0].trim(), more = text.split("\n").slice(1).join("\n").trim() || null;
  if (mode === "ask" || mode === "ask-page") {
    const askers = (S.can_ask || []).filter(hd => !ui.askSkip[hd]);
    if (!askers.length) { toast("Nobody can answer yet", "Only AIs in Claude Code, Codex or opencode can answer here."); return; }
    await act("council.ask", { question: text, seats: askers, follow_up: ui.followUp || null }, { button: btn, title: "Asked the table",
      body: askers.length > 1 ? "Each AI answers on its own first, then they rank each other's answers." : "One AI answers. Add more AIs for a real council.",
      after: res => { clear(); ui.followUp = null; if (res && res.data && res.data.id) go("#/q/" + res.data.id); } });
  } else if (mode === "plan" || mode === "quick") {
    await act("plan.goal", { goal: text, review: level, mode: mode === "quick" ? "quick" : "full", auto: !!ui.autoLock },
      { button: btn, title: mode === "quick" ? "On it" : "Planning started", body: mode === "quick" ? "One AI is splitting it into tasks now." : "Each AI now writes its own plan.", after: clear });
  } else if (mode === "note") await act("memory.add", { text }, { button: btn, title: "Sent to your AIs", body: "Every AI reads it the next time it checks in.", after: clear });
  else if (mode === "problem") await act("alert.raise", { level: 3, title: fit(first, 140), description: more }, { button: btn, title: "Your AIs have been told", after: clear });
  else if (mode === "task") await act("task.file", { title: fit(first, 140), summary: more }, { button: btn, title: "Task added", body: "It waits in Work they found until you add it.", after: clear });
}

/* ---------------------------------------------------------------- what clicks and keys do */

const SB_ACTIONS = {
  "close-modal": sbCloseModal,
  menu: () => document.body.classList.toggle("menu-open"),
  theme: () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"),
  "set-theme": el => setTheme(el.dataset.theme),
  search: sbPalette,
  pause: () => act(S.project.frozen ? "admin.unfreeze" : "admin.freeze", S.project.frozen ? {} : { reason: "paused from Sabha" }, { title: S.project.frozen ? "The council is moving again" : "A little breathing room. Council paused." }),
  earlier: el => loadEarlier(el),
  mode: () => sbShowModal(sbModalHead("How would you like to begin?") + `<div class="choice-list">${sbModes().map(([m, title, ic, sub]) => `<button data-action="set-mode" data-mode="${m}" class="choice-row ${sbMode() === m ? "selected" : ""}">${pi(ic)}<span><strong>${title}</strong><small>${esc(sub)}</small></span>${pi(sbMode() === m ? "check" : "chevron")}</button>`).join("")}</div>`),
  "set-mode": el => { const m = el.dataset.mode; if (m === "plan" || m === "quick") { ui.compose = "goal"; ui.planMode = m === "quick" ? "quick" : "full"; } else ui.compose = m; sbCloseModal(); render(); const t = document.getElementById("message-input"); if (t) t.focus(); },
  depth: () => sbShowModal(sbModalHead("How carefully should we look?") + `<div class="choice-list">${[["low", "Light", "Tests are the gate."], ["mid", "Standard", "Independent review from another model family."], ["high", "Thorough", "Full diff review, with every finding addressed."]].map(([k, t, sub]) => `<button data-action="pick-depth" data-depth="${k}" class="choice-row ${(ui.level || S.project.review) === k ? "selected" : ""}">${pi("review")}<span><strong>${t}</strong><small>${sub}</small></span>${pi((ui.level || S.project.review) === k ? "check" : "chevron")}</button>`).join("")}</div><label class="approval-confirm"><input type="checkbox" data-action="auto-lock" ${ui.autoLock ? "checked" : ""}>Start without asking me (the test commands run without you reading them first)</label>`),
  "pick-depth": el => { ui.level = el.dataset.depth; sbCloseModal(); render(); },
  "auto-lock": el => { ui.autoLock = el.checked; },
  "set-depth": el => act("admin.config_set", { key: "review.level", value: el.dataset.depth }, { title: "Review depth saved", body: "It applies to new plans." }),
  "toggle-asker": el => { const hd = el.dataset.id; if (ui.askSkip[hd]) delete ui.askSkip[hd]; else ui.askSkip[hd] = true; render(); },
  "no-follow": () => { ui.followUp = null; render(); },
  "new-question": () => { ui.followUp = null; go("#/council"); setTimeout(() => { const t = document.getElementById("council-input"); if (t) { t.value = ""; t.focus(); } }, 0); },
  "council-tab": el => { ui.ctab[el.dataset.id] = el.dataset.tab; render(); },
  "follow-up": el => { ui.followUp = el.dataset.id; render(); const t = document.getElementById("council-input"); if (t) { t.focus(); t.scrollIntoView({ behavior: "smooth", block: "center" }); } },
  "copy-answer": el => { const d = cache.council[el.dataset.id]; if (d && d.final) copyText(d.final, "The answer is on your clipboard."); },
  "build-answer": el => {
    const d = cache.council[el.dataset.id];
    if (!d) return;
    ui.compose = "goal"; ui.planMode = "full";
    go("#/room");
    setTimeout(() => { const t = document.getElementById("message-input"); if (t) { t.value = `${d.question}\n\nWhat the AIs agreed on (from ${d.id}):\n${(d.final || "").slice(0, 3200)}`; t.focus(); } }, 50);
    toast("The answer is in the message box", "Edit it into the goal you want, then send.");
  },
  "stop-question": el => act("council.cancel", { id: el.dataset.id }, { title: "Stopped", after: () => { delete cache.council[el.dataset.id]; } }),
  "plan-details": () => go("#/plandetail"),
  "new-goal": () => sbShowModal(sbModalHead("Give your council a direction.", "What would you like to make possible?") + `<form id="goal-form"><label class="field-label" for="goal-input">Your goal</label><textarea id="goal-input" rows="4" required placeholder="Say what, where, and how you'll know it works…"></textarea><div class="insight-note">${pi("council")}Each AI writes a plan without seeing the others', they comment on each other's, and bring you one plan. Nothing is built before you approve it.</div><div class="dialog-footer"><button class="btn quiet" data-action="close-modal">Cancel</button><button class="btn primary" type="submit">Consider this together ${pi("arrow")}</button></div></form>`),
  "approve-plan": el => act("plan.lock", {}, { button: el, title: "Plan approved. The AIs start building.", after: () => { ui.approvalReady = false; go("#/room"); } }),
  "task-layout": el => { ui.tlayout = el.dataset.layout; render(); },
  "task-filter": el => { ui.tfilter = el.dataset.filter; render(); },
  "activity-filter": el => { ui.afilter = el.dataset.filter; render(); },
  "search-older": () => go("#/history"),
  "export-activity": () => {
    const text = [`SABHA · ${S.project.name}`, "", ...allEvents().slice().reverse().map(e => { const m = say(e); return m ? `${e.day} ${e.at} · ${displayName(e.actor)} · ${plainText(m.marker || m.text || e.text)}` : null; }).filter(Boolean)].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    a.download = `sabha-activity-${S.project.name}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  },
  "settings-anchor": el => { const t = document.getElementById(el.dataset.anchor); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); document.querySelectorAll(".settings-nav a").forEach(a => a.classList.toggle("active", a === el)); },
  "open-project": () => go("#/switch"),
};

document.addEventListener("click", e => {
  if (!e.target.closest || !e.target.closest(".sabha, #modal")) return;
  const goEl = e.target.closest("[data-go]");
  if (goEl) { e.preventDefault(); sbCloseModal(); document.body.classList.remove("menu-open"); go(goEl.dataset.go); return; }
  const v = e.target.closest("[data-view]");
  if (v) { e.preventDefault(); sbCloseModal(); document.body.classList.remove("menu-open"); go(SB_HASH[v.dataset.view] || "#/room"); return; }
  const a = e.target.closest("[data-action]");
  if (a && SB_ACTIONS[a.dataset.action]) {
    if (a.tagName !== "INPUT") e.preventDefault();
    SB_ACTIONS[a.dataset.action](a, e);
  }
});
document.addEventListener("submit", e => {
  const f = e.target;
  if (f.id === "composer") { e.preventDefault(); sbSend(document.getElementById("message-input").value, sbMode(), f.querySelector(".send-button")); }
  else if (f.id === "question-form") { e.preventDefault(); sbSend(document.getElementById("council-input").value, "ask-page", f.querySelector("button[type=submit]")); }
  else if (f.id === "goal-form") { e.preventDefault(); const g = document.getElementById("goal-input").value; sbCloseModal(); ui.compose = "goal"; ui.planMode = "full"; sbSend(g, "plan", null).then(() => go("#/plan")); }
});
document.addEventListener("input", e => {
  if (e.target.id === "task-search") { ui.tsearch = e.target.value; const l = document.getElementById("task-list"); if (l && S.plan) l.innerHTML = sbTaskList(sbTasks().filter(t => t.plan === S.plan.id)); }
  if (e.target.id === "activity-search") { ui.asearch = e.target.value; clearTimeout(ui.asearchTimer); ui.asearchTimer = setTimeout(render, 250); }
  if (e.target.id === "command-input") {
    const v = e.target.value.toLowerCase();
    document.querySelectorAll("#command-results [data-search-text]").forEach(el => { el.hidden = !el.dataset.searchText.includes(v); });
  }
});
document.addEventListener("change", e => {
  if (e.target.id === "approval-confirm") { ui.approvalReady = e.target.checked; const b = document.querySelector('[data-action="approve-plan"]'); if (b) b.disabled = !ui.approvalReady; }
});
document.addEventListener("keydown", e => {
  if (e.target.id === "message-input" && e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); document.getElementById("composer").requestSubmit(); }
  if (e.target.id === "council-input" && e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); document.getElementById("question-form").requestSubmit(); }
  if (e.target.id === "command-input" && e.key === "Enter") { e.preventDefault(); const b = document.querySelector("#command-results button:not([hidden])"); if (b) b.click(); }
});
