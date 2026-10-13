/* Roundtable dashboard. No framework, no build step: plain DOM, polled state.
   Everything shown comes from /api/state; every change goes through /api/action
   (a Roundtable operation, as the human) or /api/do (set up, start, connect). */
"use strict";

const TOKEN = document.querySelector('meta[name="rt-token"]').content;
const APP = document.getElementById("app");
const TOASTS = document.getElementById("toasts");

let S = null;            // last state from the server
let lastJSON = "";
let route = parseRoute();
let navOpen = false;
const cache = { task: {}, diff: {}, doctor: null, log: null, logKey: "" };
const ui = {
  taskFilter: "active", taskKind: "", taskSearch: "", fileOpen: false, linkOpen: false, editOpen: false,
  started: {}, preview: {}, reviewPoints: {}, cancelPlan: false, confirm: {},
};

/* ---------------------------------------------------------------- small helpers */

function store(key, value) {
  try { if (value === undefined) return JSON.parse(localStorage.getItem(key) || "null"); localStorage.setItem(key, JSON.stringify(value)); }
  catch (e) { return null; }
  return value;
}

function h(tag, props, ...kids) {
  const el = tag === "svg" || props && props.svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === undefined || v === null || v === false || k === "svg") continue;
      if (k === "class") el.setAttribute("class", v);
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "value") el.value = v;
      else if (k === "checked") el.checked = !!v;
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function s(tag, attrs, ...kids) { return h(tag, Object.assign({ svg: true }, attrs || {}), ...kids); }

function icon(name, cls) {
  const svg = s("svg", { class: "icon" + (cls ? " " + cls : ""), "aria-hidden": "true" });
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#i-" + name);
  svg.append(use);
  return svg;
}

function num(n) { return (n || 0).toLocaleString(); }
function plural(n, one, many) { return `${n} ${n === 1 ? one : (many || one + "s")}`; }
function chip(text, tone) { return h("span", { class: "chip " + (tone || "idle") }, text); }
function prio(p) { return h("span", { class: "prio p" + p, title: ["Urgent", "High", "Normal", "Low", "Someday"][p] + " priority" }, "P" + p); }

const TASK_TONE = { backlog: "you", open: "idle", ready: "idle", claimed: "work", changes_requested: "warn", proving: "work",
  in_review: "work", merge_blocked: "warn", done: "ok", cancelled: "idle" };

function parseRoute() {
  const parts = (location.hash || "#/overview").replace(/^#\/?/, "").split("/").filter(Boolean);
  return { page: parts[0] || "overview", sub: decodeURIComponent(parts[1] || "") };
}
function go(hash) { if (location.hash === hash) render(); else location.hash = hash; }

function toast(title, body, opts) {
  opts = opts || {};
  const t = h("div", { class: "toast" + (opts.error ? " err" : ""), role: opts.error ? "alert" : "status" },
    h("strong", { text: title }), body ? h("p", { class: "pre", text: body }) : null, opts.copy ? copyBox(opts.copy) : null);
  TOASTS.append(t);
  setTimeout(() => t.remove(), opts.error || opts.copy ? 12000 : 4500);
}

function copyBox(text) {
  const btn = h("button", { type: "button", title: "Copy", "aria-label": "Copy to clipboard" }, icon("copy", "sm"));
  btn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); btn.replaceChildren(icon("check", "sm")); setTimeout(() => btn.replaceChildren(icon("copy", "sm")), 1500); }
    catch (e) { toast("Could not copy", "Select the text and copy it yourself."); }
  });
  return h("div", { class: "copybox" }, h("code", { text }), btn);
}

/* ---------------------------------------------------------------- server calls */

async function getJSON(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  return r.json();
}

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ token: TOKEN }, body)) });
  try { return await r.json(); } catch (e) { return { ok: false, message: "The dashboard did not answer. Is `rt ui` still running?" }; }
}

function busy(btn, on) {
  if (!btn) return;
  btn.disabled = on;
  btn.classList.toggle("busy", on);
}

function showResult(res, okTitle) {
  if (res.ok) {
    const first = (res.text || "").split("\n")[0];
    toast(okTitle || "Done", okTitle ? first : (res.text || "").split("\n").slice(1).join("\n"));
    return true;
  }
  const cmd = res.command || (res.data && res.data.command);
  toast(res.message || "That did not work", res.hint || "", { error: true, copy: cmd || null });
  return false;
}

async function act(op, params, opts) {
  opts = opts || {};
  busy(opts.button, true);
  const res = await post("/api/action", { op, params: params || {} });
  busy(opts.button, false);
  const ok = showResult(res, opts.title || capital((res.text || "Done").split("\n")[0]));
  if (ok && opts.after) opts.after(res);
  await refresh(true);
  return res;
}

async function special(kind, body, opts) {
  opts = opts || {};
  busy(opts.button, true);
  const res = await post("/api/do", Object.assign({ kind }, body || {}));
  busy(opts.button, false);
  if (!opts.silent) showResult(res, opts.title || capital((res.text || "Done").split("\n")[0]));
  if (res.ok && opts.after) opts.after(res);
  await refresh(true);
  return res;
}

function capital(t) { t = String(t || ""); return t.charAt(0).toUpperCase() + t.slice(1); }

async function refresh(force) {
  let next;
  try { next = await getJSON("/api/state"); }
  catch (e) { if (S) toast("Lost contact with the dashboard", "Start it again with: rt ui", { error: true }); return; }
  if (route.page === "tasks" && route.sub && /^T/i.test(route.sub)) await loadTask(route.sub);
  const json = JSON.stringify(next);
  if (!force && json === lastJSON) return;
  lastJSON = json;
  S = next;
  render();
}

async function loadTask(id) {
  try { cache.task[id] = await getJSON("/api/task?id=" + encodeURIComponent(id)); } catch (e) { /* shown as missing */ }
}

/* ---------------------------------------------------------------- render with input preservation */

function snapshot() {
  const out = { fields: {}, focus: null, open: {}, scroll: window.scrollY };
  APP.querySelectorAll("[data-k]").forEach(el => {
    out.fields[el.dataset.k] = el.type === "checkbox" || el.type === "radio" ? { checked: el.checked } : { value: el.value };
  });
  APP.querySelectorAll("details[data-k]").forEach(d => { out.open[d.dataset.k] = d.open; });
  const a = document.activeElement;
  if (a && a.dataset && a.dataset.k) out.focus = { k: a.dataset.k, start: a.selectionStart, end: a.selectionEnd };
  return out;
}

function restore(snap, samePage) {
  if (!samePage) return;
  APP.querySelectorAll("[data-k]").forEach(el => {
    const f = snap.fields[el.dataset.k];
    if (!f) return;
    if ("checked" in f) el.checked = f.checked; else if (el.tagName !== "DETAILS") el.value = f.value;
  });
  APP.querySelectorAll("details[data-k]").forEach(d => { if (d.dataset.k in snap.open) d.open = snap.open[d.dataset.k]; });
  if (snap.focus) {
    const el = APP.querySelector(`[data-k="${CSS.escape(snap.focus.k)}"]`);
    if (el) { el.focus(); try { if (snap.focus.start != null) el.setSelectionRange(snap.focus.start, snap.focus.end); } catch (e) { /* not a text field */ } }
  }
  window.scrollTo(0, snap.scroll);
}

let renderedKey = "";
function render() {
  if (!S) return;
  const key = S.mode + ":" + route.page + ":" + route.sub;
  const snap = snapshot();
  const same = key === renderedKey;
  renderedKey = key;
  APP.replaceChildren(S.mode === "setup" ? setupScreen(S) : shell());
  restore(snap, same);
  if (!same) { window.scrollTo(0, 0); const h1 = APP.querySelector("h1"); if (h1 && document.activeElement === document.body) h1.setAttribute("tabindex", "-1"); }
}

/* ---------------------------------------------------------------- shell */

const NAV = [
  ["overview", "Overview", "table"], ["plan", "Plan", "plan"], ["tasks", "Tasks", "tasks"], ["reviews", "Reviews", "review"],
  ["alerts", "Alerts and votes", "alert"], ["models", "Models", "models"], null,
  ["usage", "Usage", "usage"], ["memory", "Memory", "memory"], ["activity", "Activity", "activity"], ["settings", "Settings", "settings"],
  ["guide", "Guide", "guide"],
];

const PAGES = {};

function shell() {
  const p = S.project;
  const c = S.counts;
  const counts = { overview: [c.needs, false], tasks: [c.backlog, true], reviews: [c.reviews, false], alerts: [c.alerts, false] };
  const page = PAGES[route.page] ? route.page : "overview";
  const nav = h("ul", { class: "nav" }, NAV.map(item => {
    if (!item) return h("li", { class: "nav-sep", role: "separator" });
    const [id, label, ic] = item;
    const [n, quiet] = counts[id] || [0, false];
    return h("li", null, h("a", { href: "#/" + id, "aria-current": id === page ? "page" : null, onclick: () => { navOpen = false; } },
      icon(ic), h("span", { text: label }), n ? h("span", { class: "count" + (quiet ? " quiet" : ""), "aria-label": `${n} waiting` }, n) : null));
  }));
  const theme = store("rt.theme") || "auto";
  const rail = h("aside", { class: "rail", "aria-label": "Roundtable" },
    h("div", { class: "brand" }, h("img", { src: "/icon.svg", alt: "" }), "Roundtable"),
    h("button", { class: "project-switch", type: "button", onclick: () => go("#/switch"), title: "Open another project" },
      h("span", { text: p.name }), h("small", { text: p.root })),
    h("nav", null, nav),
    h("div", { class: "rail-foot" }, h("span", { text: "v" + p.version }),
      h("button", { type: "button", title: "Theme: " + theme, "aria-label": "Change theme (now " + theme + ")", onclick: cycleTheme },
        icon(theme === "dark" ? "moon" : "sun", "sm"))));
  const stop = p.frozen
    ? h("button", { class: "primary", type: "button", onclick: e => act("admin.unfreeze", {}, { button: e.currentTarget, title: "Models can work again" }) }, icon("play", "sm"), "Let models work again")
    : h("button", { class: "danger", type: "button", onclick: e => confirmStop(e.currentTarget) }, icon("stop", "sm"), "Stop all models");
  const title = (NAV.find(n => n && n[0] === page) || [0, page === "switch" ? "Open a project" : "Overview"])[1];
  const top = h("header", { class: "topbar" },
    h("button", { class: "quiet menu-btn", type: "button", "aria-label": "Menu", onclick: () => { navOpen = !navOpen; render(); } }, icon("menu")),
    h("div", { class: "where" }, h("strong", { text: p.name }), h("span", { text: S.plan && !["done", "cancelled"].includes(S.plan.stage) ? `Plan ${S.plan.id}: ${S.plan.stage_label}` : title })),
    stop);
  const frozen = p.frozen ? h("div", { class: "frozen-bar", role: "alert" }, icon("stop"), "All models are stopped.", h("span", { text: p.frozen_reason })) : null;
  const content = h("main", { class: "content", id: "content" }, (PAGES[page] || PAGES.overview)(S));
  return h("div", { class: "shell" + (navOpen ? " nav-open" : "") }, rail, h("div", { class: "main" }, frozen, top, content));
}

function cycleTheme() {
  const order = ["auto", "light", "dark"];
  const next = order[(order.indexOf(store("rt.theme") || "auto") + 1) % 3];
  store("rt.theme", next);
  applyTheme();
  render();
}
function applyTheme() {
  const t = store("rt.theme") || "auto";
  if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
}

function confirmStop(btn) {
  if (!ui.confirm.stop) { ui.confirm.stop = true; btn.textContent = "Click again to stop every model"; setTimeout(() => { ui.confirm.stop = false; render(); }, 4000); return; }
  ui.confirm.stop = false;
  act("admin.freeze", { reason: "stopped from the dashboard" }, { button: btn, title: "All models stopped" });
}

function pageHead(title, lead, ...right) {
  return h("div", { class: "page-head" }, h("div", null, h("h1", { text: title }), lead ? h("p", { text: lead }) : null), right.length ? h("div", { class: "btn-row" }, right) : null);
}

function panel(title, sub, ...body) {
  return h("section", { class: "panel" },
    title ? h("header", null, h("div", null, h("h2", { text: title }), sub ? h("p", { text: sub }) : null)) : null,
    h("div", { class: "panel-body" }, body));
}

/* ---------------------------------------------------------------- set-up screen */

function setupScreen(st) {
  const f = st.setup;
  const notes = [];
  let can = f.exists;
  if (!f.exists) { notes.push(h("p", { class: "note warn", text: "This folder does not exist." })); }
  else if (f.worktree_of) { can = false; notes.push(h("p", { class: "note warn", text: `This is a model's working copy. Set up Roundtable in the main folder instead: ${f.worktree_of}` })); }
  else if (f.inside) { can = false; notes.push(h("p", { class: "note warn", text: `This folder is inside a git repository. Set up Roundtable at its top folder: ${f.toplevel}` })); }
  else if (!f.git) { notes.push(h("p", { class: "note warn", text: "No git here. Roundtable still works, but every model shares this one folder. For separate working copies, reviews of real diffs and automatic merges, run `git init` and make a first commit, then reload." })); }
  else if (!f.has_commits) { notes.push(h("p", { class: "note warn", text: "This git repository has no commits yet. Make a first commit before adding coding models (their working copies start from it)." })); }
  else { notes.push(h("p", { class: "note ok", text: `Git repository on branch ${f.branch || "(detached)"}. Each coding model will get its own working copy next to this folder, and finished work merges into ${f.branch || "your branch"}.` })); }
  const folderIn = h("input", { type: "text", id: "open-folder", "data-k": "open-folder", value: f.folder, spellcheck: "false", autocomplete: "off" });
  const recent = st.recent && st.recent.length ? h("div", { class: "field" }, h("label", { text: "Recent projects" }),
    h("ul", { class: "rows" }, st.recent.map(r => h("li", { class: "btn-row" }, h("button", { type: "button", onclick: e => special("open", { folder: r.root }, { button: e.currentTarget, title: "Opened " + r.name }) }, icon("folder", "sm"), r.name), h("span", { class: "faint", text: r.root }))))) : null;
  return h("div", { class: "setup" }, h("section", { class: "panel" }, h("div", { class: "panel-body" },
    h("img", { src: "/icon.svg", alt: "", width: "40", height: "40" }),
    h("h1", { text: "Set up Roundtable here" }),
    h("p", { class: "lead", text: "Several AI models will plan, build and review this project together, each in its own app. Roundtable only adds a hidden .roundtable folder; it never changes your files." }),
    h("dl", { class: "kv" }, h("dt", { text: "Folder" }), h("dd", { class: "mono", text: f.folder })),
    h("div", { class: "stack" }, h("div", null, notes),
      h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", disabled: !can, onclick: e => special("init", { folder: f.folder }, { button: e.currentTarget, title: "Roundtable is set up" }) }, "Set up Roundtable in this folder")),
      h("div", { class: "field" }, h("label", { for: "open-folder", text: "Or open another folder" }),
        h("div", { class: "btn-row" }, folderIn, h("button", { type: "button", onclick: e => special("open", { folder: folderIn.value.trim() }, { button: e.currentTarget, title: "Opened" }) }, "Open"))),
      recent))));
}

PAGES.switch = st => h("div", { class: "stack" },
  pageHead("Open a project", "Roundtable keeps one table per project folder. Switch to another one, or set one up."),
  panel(null, null, (() => {
    const input = h("input", { type: "text", id: "switch-folder", "data-k": "switch-folder", placeholder: "/home/you/projects/app", spellcheck: "false" });
    return h("div", { class: "field" }, h("label", { for: "switch-folder", text: "Folder" }),
      h("div", { class: "btn-row" }, input, h("button", { class: "primary", type: "button", onclick: e => special("open", { folder: input.value.trim() }, { button: e.currentTarget, title: "Opened", after: () => go("#/overview") }) }, "Open")),
      h("p", { class: "help", text: "If the folder has no Roundtable project yet, you can set one up there next." }));
  })()));

/* ---------------------------------------------------------------- overview */

PAGES.overview = st => {
  const needs = st.needs;
  const decide = needs.filter(n => n.tone !== "info");
  const info = needs.filter(n => n.tone === "info");
  const gs = st.getting_started;
  const showGs = gs.some(x => !x.done) && !store("rt.gs.hidden." + st.project.root);
  const lead = st.plan && !["done", "cancelled"].includes(st.plan.stage) ? `Goal: ${st.plan.goal}` : "Several models, one project. You chair the table.";
  const working = st.tasks.filter(t => ["claimed", "changes_requested", "proving", "in_review", "merge_blocked"].includes(t.status));
  return h("div", { class: "stack" },
    pageHead("Overview", lead),
    h("div", { class: "grid-2" },
      h("div", { class: "stack" },
        panel("Needs you", decide.length ? plural(decide.length, "thing") + " waiting for you" : info.length ? "Nothing urgent. Next steps:" : "Nothing is waiting for you right now.",
          needs.length ? h("ul", { class: "needs" }, [...decide, ...info].map(needItem)) :
            h("div", { class: "all-clear" }, icon("check"), "The models are working. New decisions show up here, and in your notifications if rt watch is running.")),
        showGs ? panel("Getting started", "Five steps from an empty table to merged work.",
          h("ol", { class: "steps" }, gs.map((x, i) => h("li", { class: (x.done ? "done" : "") + (i === gs.findIndex(y => !y.done) ? " next" : "") },
            h("div", null, h("strong", { text: x.title }), x.hint ? h("small", { text: x.hint }) : null)))),
          h("div", { class: "btn-row" }, h("button", { class: "quiet", type: "button", onclick: () => { store("rt.gs.hidden." + st.project.root, true); render(); } }, "Hide these steps"))) : null),
      h("div", { class: "stack" },
        h("section", { class: "panel table-panel", "aria-label": "The table" }, theTable(st), legend()),
        panel("In progress", working.length ? plural(working.length, "task") + " moving" : null,
          working.length ? h("ul", { class: "rows" }, working.map(t => h("li", { class: "btn-row" },
            h("a", { class: "id", href: "#/tasks/" + t.id, text: t.id }), h("span", { text: t.title }), chip(t.status_label, TASK_TONE[t.status]), t.owner ? h("span", { class: "faint", text: t.owner }) : null)))
            : h("p", { class: "empty", text: st.tasks.length ? "No task is being worked on right now." : "No tasks yet. They appear when you lock a plan." })))),
    panel("Latest activity", null, feed(st.events.slice(0, 12)), h("div", { class: "btn-row" }, h("a", { href: "#/activity", class: "small", text: "All activity" }))));
};

function needItem(n) {
  const mark = { decide: "plan", warn: "alert", stop: "stop", info: "chevron" }[n.tone] || "chevron";
  const actions = (n.actions || []).map(a => a.go
    ? h("button", { type: "button", class: a.style || "", onclick: () => go("#/" + a.go) }, a.label)
    : h("button", { type: "button", class: a.style || "", onclick: e => act(a.op, a.params, { button: e.currentTarget }) }, a.label));
  return h("li", { class: "need " + n.tone }, h("div", { class: "mark" }, icon(mark, "sm")),
    h("h3", { text: n.title }), n.body ? h("p", { text: n.body }) : null, actions.length ? h("div", { class: "btn-row" }, actions) : null);
}

function seatState(seat) {
  if (seat.status === "paused") return ["paused", "paused"];
  if (!seat.joined_ever) return ["idle", "not started"];
  if (seat.tasks.length) return ["working", "on " + seat.tasks.join(", ")];
  if (seat.live) return ["live", seat.doing || "at the table"];
  return ["idle", "away " + seat.seen.replace(" ago", "")];
}

function theTable(st) {
  const W = 420, H = 372, cx = W / 2, cy = 190, rx = 118, ry = 70;
  const seats = st.seats.filter(x => x.status !== "removed");
  const svg = s("svg", { class: "table-svg", viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": seats.length ? "The table: " + seats.map(x => `${x.handle} ${seatState(x)[1]}`).join("; ") : "The table is empty" });
  const defs = s("defs", null, s("marker", { id: "arrow", viewBox: "0 0 8 8", refX: "6", refY: "4", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" },
    s("path", { d: "M0 0L8 4L0 8z", class: "chord-head" })));
  svg.append(defs);
  svg.append(s("ellipse", { class: "cloth", cx, cy, rx, ry }), s("ellipse", { class: "cloth-inner", cx, cy, rx: rx - 12, ry: ry - 10 }));
  const pos = {};
  const n = seats.length;
  seats.forEach((seat, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(n, 1);
    pos[seat.handle] = { x: cx + (rx + 54) * Math.cos(a), y: cy + (ry + 42) * Math.sin(a), a };
  });
  // chords: who reviews or critiques whom right now
  const owners = {};
  st.tasks.forEach(t => { if (t.owner) owners[t.id] = t.owner; });
  const chords = [];
  if (st.plan && st.plan.stage === "critique") (st.plan.critique_pairs || []).forEach(pair => chords.push(pair));
  st.tasks.filter(t => t.status === "in_review").forEach(t => (t.reviewers || []).forEach(r => chords.push([r, t.owner])));
  chords.forEach(([from, to]) => {
    if (!pos[from] || !pos[to] || from === to) return;
    const A = pos[from], B = pos[to];
    svg.append(s("path", { class: "chord", d: `M${A.x} ${A.y} Q${cx} ${cy} ${B.x} ${B.y}`, "marker-end": "url(#arrow)" }));
  });
  // centre: what the table is doing
  const plan = st.plan;
  const done = st.tasks.filter(t => t.status === "done" && t.kind !== "epic").length;
  const total = st.tasks.filter(t => !["cancelled", "backlog"].includes(t.status) && t.kind !== "epic").length;
  const line1 = !seats.length ? "No one at the table yet" : !plan || ["done", "cancelled"].includes(plan.stage) ? (done ? "Plan finished" : "Waiting for a goal")
    : plan.stage === "locked" ? `Building: ${done} of ${total} done` : plan.stage_label;
  const line2 = plan && plan.stage !== "locked" && !["done", "cancelled"].includes(plan.stage) ? `for ${plan.since.replace(" ago", "")}` : seats.length ? plural(seats.length, "model") : "Add models to begin";
  svg.append(s("text", { class: "phase", x: cx, y: cy - 2, "text-anchor": "middle" }, fit(line1, 30)),
    s("text", { class: "phase-sub", x: cx, y: cy + 18, "text-anchor": "middle" }, line2));
  seats.forEach(seat => {
    const p = pos[seat.handle];
    const [cls, note] = seatState(seat);
    const g = s("a", { href: "#/models/" + seat.handle, "aria-label": `${seat.handle}: ${note}` });
    g.append(s("circle", { class: "seat-disc " + cls, cx: p.x, cy: p.y, r: 21 }),
      s("text", { class: "seat-mono", x: p.x, y: p.y + 4.5, "text-anchor": "middle" }, monogram(seat.handle)));
    const below = Math.sin(p.a) > -0.3;
    const ty = below ? p.y + 37 : p.y - 46;
    g.append(s("text", { class: "seat-name", x: p.x, y: ty, "text-anchor": "middle" }, seat.handle),
      s("text", { class: "seat-note", x: p.x, y: ty + 15, "text-anchor": "middle" }, fit(note, 22)));
    svg.append(g);
  });
  return svg;
}

function monogram(handle) { const c = handle.replace(/[^a-z0-9]/gi, ""); return (c.charAt(0).toUpperCase() + (c.charAt(1) || "")).slice(0, 2); }
function fit(t, n) { t = String(t || ""); return t.length > n ? t.slice(0, n - 1) + "…" : t; }

function legend() {
  return h("div", { class: "legend", "aria-hidden": "true" },
    h("span", { class: "live" }, h("i"), "At the table"), h("span", { class: "working" }, h("i"), "Working on a task"),
    h("span", { class: "idle" }, h("i"), "Away or not started"), h("span", { class: "chord" }, h("i"), "Reviewing"));
}

function feed(events) {
  if (!events.length) return h("p", { class: "empty", text: "Nothing has happened yet." });
  const items = [];
  let day = "";
  events.forEach(e => {
    if (e.day !== day) { day = e.day; items.push(h("li", { class: "day", text: day })); }
    let text = e.text;
    if (text.startsWith(e.actor + " ")) text = text.slice(e.actor.length + 1);
    if (e.actor === "human" && text.startsWith("the human ")) text = text.slice(10);
    if (e.task && text.startsWith(e.task)) text = text.slice(e.task.length).replace(/^:? ?/, "");
    items.push(h("li", { class: e.level >= 4 ? "hi" : "" }, h("span", { class: "t", text: e.at }), h("span", { class: "who", text: e.actor === "human" ? "you" : e.actor }),
      h("span", { class: "what" }, e.task ? [h("a", { class: "id", href: "#/tasks/" + e.task, text: e.task }), " "] : null, text)));
  });
  return h("ul", { class: "feed" }, items);
}

/* ---------------------------------------------------------------- plan */

const STAGE_STEPS = [["drafting", "Plans"], ["critique", "Critique"], ["merging", "Merge"], ["proposed", "Approval"], ["awaiting_human", "Your lock"], ["locked", "Building"]];

PAGES.plan = st => {
  const p = st.plan;
  if (!p || ["done", "cancelled"].includes(p.stage)) return h("div", { class: "stack" },
    pageHead("Plan", "Tell the models what to build. Each writes a plan on its own, they critique each other without knowing who wrote what, and agree on one plan for you to lock."),
    goalForm(st), p ? panel(`Last plan: ${p.stage === "done" ? "finished" : "cancelled"}`, p.goal) : null);
  const at = STAGE_STEPS.findIndex(x => x[0] === (p.stage === "voting" ? "proposed" : p.stage));
  const line = h("ol", { class: "stage-line", "aria-label": "Planning stages" }, STAGE_STEPS.map(([id, label], i) =>
    h("li", { class: i < at ? "past" : i === at ? "now" : "", "aria-current": i === at ? "step" : null, text: label })));
  const people = h("div", { class: "table-wrap" }, h("table", { class: "data" },
    h("thead", null, h("tr", null, h("th", { text: "Model" }), h("th", { text: "Own plan" }), h("th", { text: "Critiques" }), h("th", { text: "Merged plan" }))),
    h("tbody", null, p.people.map(x => h("tr", null,
      h("td", null, h("strong", { text: x.seat }), x.chair ? h("span", { class: "faint", text: " (chair)" }) : null),
      h("td", null, x.planner ? (x.drafted ? chip("written", "ok") : chip("writing", "work")) : h("span", { class: "faint", text: "not a planner" })),
      h("td", null, x.critiques ? `${x.critiques_done} of ${x.critiques}` : h("span", { class: "faint", text: "none" })),
      h("td", null, x.approval ? chip(x.approval.decision === "approve" ? "approved" : "objected", x.approval.decision === "approve" ? "ok" : "warn") : x.chair && p.stage !== "drafting" ? h("span", { class: "faint", text: "wrote it" }) : h("span", { class: "faint", text: "-" })))))));
  const actions = [];
  if (p.stage === "awaiting_human") actions.push(lockBlock(p, false));
  else if (["proposed", "voting"].includes(p.stage) && p.tasks.length) actions.push(lockBlock(p, true));
  if (p.overdue) actions.push(h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => act("plan.continue", {}, { button: e.currentTarget }) }, "Go on without the missing plans")));
  return h("div", { class: "stack" },
    pageHead("Plan " + p.id, p.goal),
    panel(p.stage_label, `Since ${p.since}.` + (p.revisions ? ` Revised ${plural(p.revisions, "time")}.` : ""), h("div", { class: "stack" }, line, people)),
    actions.length ? panel(p.stage === "awaiting_human" ? "Lock the plan" : "Lock early", null, actions) : null,
    p.proposal || p.tasks.length ? panel(p.proposal ? "The merged plan" : "The plan", p.chair ? `Merged by ${p.chair}.` : null,
      p.proposal ? h("p", { class: "pre prose", text: p.proposal }) : null, specTable(p.tasks)) : null,
    p.drafts.length ? panel("Each model's own plan", p.stage === "drafting" ? "Models cannot see each other's plans until every plan is in. You can." : "Shown to the models as Plan A, B, C, without names.",
      p.drafts.map(d => draftBlock(d, p))) : null,
    p.amendments.length ? panel("Proposed changes", "Models asked to change the locked plan.", h("ul", { class: "rows" }, p.amendments.map(m => h("li", null,
      h("p", null, h("strong", { text: `${m.by}: ${m.kind.replace(/_/g, " ")} ${m.task || ""}` })), h("p", { class: "muted", text: m.reason }),
      h("p", { class: "mono small pre", text: JSON.stringify(m.change) }),
      m.human ? h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => act("plan.amend_decide", { id: m.id, decision: "approve" }, { button: e.currentTarget }) }, "Approve change"),
        h("button", { type: "button", onclick: e => act("plan.amend_decide", { id: m.id, decision: "reject" }, { button: e.currentTarget }) }, "Reject")) : h("p", { class: "faint", text: "Waiting for: " + m.needs.join(", ") }))))) : null,
    cancelPlanBlock(p));
};

function lockBlock(p, early) {
  const ack = h("input", { type: "checkbox", id: "lock-ack", "data-k": "lock-ack" });
  const btn = h("button", { class: "primary", type: "button", onclick: e => {
    if (!ack.checked) { toast("Tick the box first", "These commands will run on your computer. Read them, then tick the box."); return; }
    act("plan.lock", early ? { force: true } : {}, { button: e.currentTarget, title: "Plan locked" });
  } }, early ? "Lock without waiting" : "Lock the plan");
  return h("div", { class: "stack" },
    early ? h("p", { class: "muted", text: "Not every model has approved yet. You can lock anyway; objections are listed above." }) : null,
    h("div", null, h("h3", { text: "These test commands will run on your computer" }),
      h("p", { class: "faint", text: "Roundtable runs them when a task is finished, to prove it works. Only lock if every command is safe." })),
    h("div", { class: "output", text: p.commands.length ? p.commands.join("\n") : "(no commands)" }),
    h("label", { class: "check", for: "lock-ack" }, ack, h("span", null, "I have read these commands and they are safe to run here")),
    h("div", { class: "btn-row" }, btn));
}

function specTable(specs) {
  if (!specs || !specs.length) return null;
  return h("div", { class: "table-wrap" }, h("table", { class: "data" },
    h("thead", null, h("tr", null, h("th", { text: "Task" }), h("th", { text: "Owner" }), h("th", { class: "hide-sm", text: "Files" }), h("th", { class: "hide-sm", text: "Waits for" }), h("th", { text: "Test command" }))),
    h("tbody", null, specs.map(t => h("tr", null,
      h("td", { class: "title" }, h("span", { class: "inline-list" }, t.priority !== undefined && t.priority !== 2 ? prio(t.priority) : null, t.kind && t.kind !== "task" ? h("span", { class: "tag", text: t.kind }) : null, h("strong", { text: t.title })), t.summary ? h("small", { text: t.summary }) : null),
      h("td", { text: t.owner || "anyone" }),
      h("td", { class: "hide-sm mono small", text: (t.files || []).join(", ") }),
      h("td", { class: "hide-sm", text: (t.depends_on || []).join(", ") || "-" }),
      h("td", { class: "mono small", text: (t.proof || []).join(" && ") || (t.kind === "epic" ? "(epic)" : "") }))))));
}

function draftBlock(d, p) {
  const crits = p.critiques.filter(c => c.draft === d.label);
  return h("details", { class: "draft", "data-k": "draft-" + (d.label || d.author) },
    h("summary", null, icon("chevron", "sm turn"), h("strong", { text: d.label ? `Plan ${d.label}` : "Plan" }), h("span", { class: "muted", text: `by ${d.author}` }),
      h("span", { class: "faint", text: `${plural(d.tasks.length, "task")}, ${plural(crits.length, "critique")}` })),
    h("p", { class: "pre prose", text: d.text }), specTable(d.tasks),
    crits.map(c => h("div", { class: "note" }, h("strong", { text: `Critique by ${c.critic}` }),
      h("ul", { class: "points" }, c.points.map(pt => h("li", null, h("span", { class: "verdict-" + (pt.verdict || "change"), text: (pt.verdict || "") + ": " }), pt.text))))));
}

function cancelPlanBlock(p) {
  if (["locked"].includes(p.stage) && !ui.cancelPlan) return h("div", { class: "btn-row" }, h("button", { class: "quiet", type: "button", onclick: () => { ui.cancelPlan = true; render(); } }, "Cancel this plan…"));
  if (!ui.cancelPlan) return h("div", { class: "btn-row" }, h("button", { class: "quiet", type: "button", onclick: () => { ui.cancelPlan = true; render(); } }, "Cancel this plan…"));
  const reason = h("input", { type: "text", id: "cancel-reason", "data-k": "cancel-reason", placeholder: "Why (the models will see this)" });
  return panel("Cancel the plan", "Unfinished tasks are cancelled too. Work already merged stays.",
    h("div", { class: "field" }, h("label", { for: "cancel-reason", text: "Reason" }), reason),
    h("div", { class: "btn-row" }, h("button", { class: "danger solid", type: "button", onclick: e => {
      if (!reason.value.trim()) { toast("Add a reason", "The models read it, so they know what changed."); return; }
      act("plan.cancel", { reason: reason.value.trim() }, { button: e.currentTarget, after: () => { ui.cancelPlan = false; } });
    } }, "Cancel the plan"), h("button", { type: "button", onclick: () => { ui.cancelPlan = false; render(); } }, "Keep it")));
}

function goalForm(st) {
  const planners = st.seats.filter(x => x.status === "active" && x.roles.includes("plan"));
  const goal = h("textarea", { id: "goal", "data-k": "goal", rows: "5", placeholder: "Add a search box to the log page, case-insensitive, with tests." });
  const level = st.project.review;
  const choices = [
    ["low", "Low", "No code review between models. Fastest and cheapest; tests still have to pass."],
    ["mid", "Mid", "A model from another company reviews a map of each change, and the full code of 1 task in 5 and of risky tasks."],
    ["high", "High", "Two models read every line and leave line comments. The most thorough, and several times the tokens."],
  ];
  if (!st.seats.length) return panel("Add models first", null, h("p", { class: "empty", text: "A plan needs models to write it." }),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: () => go("#/models/add") }, icon("plus", "sm"), "Add a model")));
  return panel("Start a plan", null,
    h("div", { class: "field" }, h("label", { for: "goal", text: "What should the models build?" }),
      h("span", { class: "help", text: "Be specific: what, where, and how you will know it works (which tests should pass)." }), goal),
    h("fieldset", { class: "field" }, h("legend", { text: "Who writes a plan" }), h("span", { class: "help", text: "Up to three, spread across companies, is a good default." }),
      planners.length ? h("div", { class: "choices" }, planners.map(x => h("label", { class: "check" },
        h("input", { type: "checkbox", "data-k": "planner-" + x.handle, value: x.handle, checked: true, class: "planner" }),
        h("span", null, h("strong", { text: x.handle }), h("small", { text: `${x.model}, ${x.app_label}` })))))
        : h("p", { class: "faint", text: "No model has the plan role." })),
    h("fieldset", { class: "field" }, h("legend", { text: "Review depth" }), h("span", { class: "help", text: "How much of each other's work the models read. This is separate from how hard each model thinks." }),
      h("div", { class: "choices" }, choices.map(([v, t, d]) => h("label", { class: "choice" },
        h("input", { type: "radio", name: "level", value: v, "data-k": "level-" + v, checked: v === level }), h("div", null, h("strong", { text: t }), h("span", { text: d })))))),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => {
      const text = goal.value.trim();
      if (!text) { toast("Write the goal first", "One or two sentences is enough."); goal.focus(); return; }
      const picked = [...APP.querySelectorAll("input.planner:checked")].map(x => x.value);
      const lv = (APP.querySelector('input[name="level"]:checked') || {}).value;
      act("plan.goal", { goal: text, planners: picked.length ? picked : null, review: lv }, { button: e.currentTarget, title: "Planning started" });
    } }, "Start planning")));
}

/* ---------------------------------------------------------------- tasks */

const TASK_FILTERS = [
  ["active", "Active", t => !["done", "cancelled", "backlog"].includes(t.status)],
  ["backlog", "Backlog", t => t.status === "backlog"],
  ["ready", "Ready", t => t.status === "ready"],
  ["working", "In progress", t => ["claimed", "changes_requested"].includes(t.status)],
  ["review", "Testing and review", t => ["proving", "in_review", "merge_blocked"].includes(t.status)],
  ["done", "Done", t => t.status === "done"],
  ["all", "All", () => true],
];

PAGES.tasks = st => {
  if (route.sub === "backlog") ui.taskFilter = "backlog";
  const sel = /^T/i.test(route.sub) ? route.sub.toUpperCase() : "";
  const filt = TASK_FILTERS.find(f => f[0] === ui.taskFilter) || TASK_FILTERS[0];
  const q = ui.taskSearch.trim().toLowerCase();
  let list = st.tasks.filter(filt[2]).filter(t => !ui.taskKind || t.kind === ui.taskKind)
    .filter(t => !q || (t.id + " " + t.title + " " + t.labels.join(" ") + " " + t.owner).toLowerCase().includes(q));
  const counts = {};
  TASK_FILTERS.forEach(f => { counts[f[0]] = st.tasks.filter(f[2]).length; });
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Show" }, TASK_FILTERS.map(([id, label]) =>
    h("button", { type: "button", "aria-pressed": String(ui.taskFilter === id), onclick: () => { ui.taskFilter = id; if (route.sub === "backlog") go("#/tasks"); else render(); } },
      label + (counts[id] && id !== "all" ? ` ${counts[id]}` : ""))));
  const search = h("input", { type: "search", "data-k": "task-search", placeholder: "Search tasks", "aria-label": "Search tasks", value: ui.taskSearch,
    oninput: e => { ui.taskSearch = e.target.value; render(); } });
  const kinds = h("select", { "aria-label": "Kind", onchange: e => { ui.taskKind = e.target.value; render(); } },
    h("option", { value: "" }, "Every kind"), ["task", "feature", "bug", "chore", "docs", "test", "epic"].map(k => h("option", { value: k, selected: ui.taskKind === k ? true : null }, k)));
  // epics first with their tasks under them
  const byParent = {};
  list.forEach(t => { if (t.parent) (byParent[t.parent] = byParent[t.parent] || []).push(t); });
  const ordered = [];
  list.filter(t => !t.parent || !list.some(x => x.id === t.parent)).forEach(t => { ordered.push([t, false]); (byParent[t.id] || []).forEach(c => ordered.push([c, true])); });
  const table = ordered.length ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
    h("thead", null, h("tr", null, h("th", { text: "" }), h("th", { text: "Task" }), h("th", { text: "Status" }), h("th", { class: "hide-sm", text: "Owner" }), h("th", { class: "hide-sm", text: "Updated" }))),
    h("tbody", null, ordered.map(([t, child]) => h("tr", { class: "clickable" + (child ? " child" : ""), "aria-selected": t.id === sel ? "true" : null, tabindex: "0",
      onclick: () => go("#/tasks/" + t.id), onkeydown: e => { if (e.key === "Enter") go("#/tasks/" + t.id); } },
      h("td", null, prio(t.priority)),
      h("td", { class: "title" }, h("strong", { text: t.title }),
        h("div", { class: "task-meta" }, h("span", { class: "id", text: t.id }), t.kind !== "task" ? h("span", { class: "tag", text: t.kind }) : null,
          t.labels.map(l => h("span", { class: "tag", text: l })), t.waits_for.length ? h("span", { text: "waits for " + t.waits_for.join(", ") }) : null)),
      h("td", null, chip(t.status_label, TASK_TONE[t.status])),
      h("td", { class: "hide-sm", text: t.owner || "-" }),
      h("td", { class: "hide-sm faint", text: t.updated })))))) :
    h("div", { class: "empty" }, h("strong", { text: st.tasks.length ? "No tasks match." : "No tasks yet." }),
      st.tasks.length ? "Try another filter." : "Tasks appear when you lock a plan, or when you or a model file one.");
  const left = h("div", { class: "stack" }, panel(null, null, h("div", { class: "toolbar" }, seg, kinds, search), table, fileForm(st)));
  const right = sel ? taskDetail(st, sel) : null;
  return h("div", { class: "stack" },
    pageHead("Tasks", "Ordered by priority. Backlog items were filed by models or by you and wait for your yes.",
      h("button", { type: "button", onclick: () => { ui.fileOpen = !ui.fileOpen; render(); } }, icon("plus", "sm"), "File a task")),
    right ? h("div", { class: "grid-split" }, left, right) : left);
};

function fileForm(st) {
  if (!ui.fileOpen) return null;
  const epics = st.tasks.filter(t => t.kind === "epic" && !["done", "cancelled"].includes(t.status));
  const f = {
    title: h("input", { type: "text", id: "f-title", "data-k": "f-title" }),
    kind: h("select", { id: "f-kind", "data-k": "f-kind" }, ["task", "feature", "bug", "chore", "docs", "test", "epic"].map(k => h("option", { value: k }, k))),
    prio: h("select", { id: "f-prio", "data-k": "f-prio" }, [0, 1, 2, 3, 4].map(p => h("option", { value: String(p), selected: p === 2 ? true : null }, `P${p} ${["urgent", "high", "normal", "low", "someday"][p]}`))),
    summary: h("textarea", { id: "f-summary", "data-k": "f-summary", rows: "3" }),
    files: h("input", { type: "text", id: "f-files", "data-k": "f-files", placeholder: "src/search.py, tests/test_search.py", spellcheck: "false" }),
    proof: h("input", { type: "text", id: "f-proof", "data-k": "f-proof", placeholder: "python -m pytest -q tests/test_search.py", spellcheck: "false" }),
    labels: h("input", { type: "text", id: "f-labels", "data-k": "f-labels", placeholder: "ui, search" }),
    parent: h("select", { id: "f-parent", "data-k": "f-parent" }, h("option", { value: "" }, "None"), epics.map(e => h("option", { value: e.id }, `${e.id} ${e.title}`))),
  };
  return h("div", { class: "stack file-form" }, h("h3", { text: "File a task" }),
    h("p", { class: "faint", text: "With files and a test command it is ready at once. Without them it waits in the backlog." }),
    h("div", { class: "form-grid" },
      h("div", { class: "field wide" }, h("label", { for: "f-title", text: "Title" }), f.title),
      h("div", { class: "field" }, h("label", { for: "f-kind", text: "Kind" }), f.kind),
      h("div", { class: "field" }, h("label", { for: "f-prio", text: "Priority" }), f.prio),
      h("div", { class: "field wide" }, h("label", { for: "f-summary", text: "What and why" }), f.summary),
      h("div", { class: "field" }, h("label", { for: "f-files", text: "Files it may change" }), h("span", { class: "help", text: "Comma separated; globs like src/** work." }), f.files),
      h("div", { class: "field" }, h("label", { for: "f-proof", text: "Test command" }), h("span", { class: "help", text: "Runs on your computer when the task is finished." }), f.proof),
      h("div", { class: "field" }, h("label", { for: "f-labels", text: "Labels" }), f.labels),
      h("div", { class: "field" }, h("label", { for: "f-parent", text: "Part of epic" }), f.parent)),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => {
      if (!f.title.value.trim()) { toast("Give it a title", ""); f.title.focus(); return; }
      act("task.file", { title: f.title.value.trim(), kind: f.kind.value, priority: Number(f.prio.value), summary: f.summary.value.trim() || null,
        files: csv(f.files.value), proof: f.proof.value.trim() ? [f.proof.value.trim()] : null, labels: csv(f.labels.value), parent: f.parent.value || null },
        { button: e.currentTarget, after: () => { ui.fileOpen = false; } });
    } }, "File task"), h("button", { type: "button", onclick: () => { ui.fileOpen = false; render(); } }, "Close")));
}

function csv(v) { const out = String(v || "").split(",").map(x => x.trim()).filter(Boolean); return out.length ? out : null; }

function taskDetail(st, id) {
  const d = cache.task[id];
  if (!d) { loadTask(id).then(render); return panel(id, "Loading…"); }
  if (d.ok === false) return panel(id, d.message || "Not found");
  const seats = st.seats.filter(x => x.roles.includes("build") && x.status === "active");
  const close = h("button", { class: "quiet", type: "button", "aria-label": "Close details", onclick: () => go("#/tasks") }, icon("x", "sm"));
  const actions = [];
  if (d.status === "backlog") actions.push(acceptForm(d, seats));
  if (d.status === "merge_blocked") actions.push(h("div", { class: "stack" }, h("p", { class: "note warn", text: d.merge_note || "Approved, but it cannot merge yet." }),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => act("task.merge", { task: d.id }, { button: e.currentTarget }) }, "Try the merge again"))));
  const editing = ui.editOpen === d.id;
  return h("aside", { class: "panel detail", "aria-label": "Task " + d.id },
    h("header", null, h("div", null, h("h2", null, h("span", { class: "id", text: d.id + " " }), d.title),
      h("p", { class: "inline-list" }, chip(d.status_label, TASK_TONE[d.status]), prio(d.priority), d.kind !== "task" ? h("span", { class: "tag", text: d.kind }) : null, d.labels.map(l => h("span", { class: "tag", text: l })))), close),
    h("div", { class: "panel-body" },
      actions.length ? h("section", null, actions) : null,
      h("section", null, h("dl", { class: "kv" },
        h("dt", { text: "Owner" }), h("dd", { text: d.owner || "anyone who claims it" }),
        d.filed_by ? [h("dt", { text: "Filed by" }), h("dd", { text: d.filed_by })] : null,
        h("dt", { text: "Review depth" }), h("dd", { text: d.review }),
        h("dt", { text: "Files" }), h("dd", { class: "mono small", text: d.files.join(", ") || "-" }),
        h("dt", { text: "Test command" }), h("dd", { class: "mono small", text: d.proof.join(" && ") || "-" }),
        d.waits_for.length ? [h("dt", { text: "Waits for" }), h("dd", null, d.waits_for.map(x => h("a", { class: "id", href: "#/tasks/" + x, text: x + " " })))] : null,
        d.links.filter(l => l.kind !== "waits_for").length ? [h("dt", { text: "Links" }), h("dd", null, d.links.filter(l => l.kind !== "waits_for").map(l => h("span", null, l.kind.replace(/_/g, " ") + " ", h("a", { class: "id", href: "#/tasks/" + l.other, text: l.other }), " ")))] : null,
        d.parent ? [h("dt", { text: "Epic" }), h("dd", null, h("a", { class: "id", href: "#/tasks/" + d.parent, text: d.parent }))] : null),
        d.summary ? h("p", { class: "pre", text: d.summary }) : null,
        d.children.length ? h("ul", { class: "rows" }, d.children.map(c => h("li", { class: "btn-row" }, h("a", { class: "id", href: "#/tasks/" + c.id, text: c.id }), c.title, chip(c.status, TASK_TONE[c.status])))) : null),
      d.proofs.length ? h("section", null, h("h4", { text: "Test runs" }), d.proofs.slice(0, 3).map(p => h("div", { class: "stack" },
        h("p", { class: "inline-list" }, chip(p.status, p.status === "passed" ? "ok" : ["running", "queued"].includes(p.status) ? "work" : "stop"), h("span", { class: "faint", text: `${p.at} by ${p.by}` })),
        p.output ? h("div", { class: "output", text: p.output }) : null))) : null,
      d.checkpoints.length ? h("section", null, h("h4", { text: "Progress notes" }), h("ul", { class: "rows" }, d.checkpoints.slice(0, 6).map(c => h("li", null,
        h("p", null, h("strong", { text: c.seat + ": " }), c.line), h("p", { class: "faint", text: `${c.at}${c.files.length ? `, ${c.files.length} files +${c.added} -${c.removed}` : ""}` }))))) : null,
      d.reviews.length ? h("section", null, h("h4", { text: "Reviews" }), h("ul", { class: "rows" }, d.reviews.map(r => h("li", null,
        h("p", { class: "inline-list" }, h("strong", { text: r.reviewer }), chip(r.verdict === "approve" ? "approved" : r.verdict === "changes" ? "changes requested" : "pending", r.verdict === "approve" ? "ok" : r.verdict === "changes" ? "warn" : "work"), h("span", { class: "faint", text: `${r.level}, round ${r.round}` })),
        r.points.length ? h("ul", { class: "points" }, r.points.map(p => h("li", { text: typeof p === "string" ? p : JSON.stringify(p) }))) : null)))) : null,
      d.comments.length ? h("section", null, h("h4", { text: "Line comments" }), h("ul", { class: "rows" }, d.comments.map(c => h("li", null,
        h("p", { class: "mono small", text: `${c.file}${c.line ? ":" + c.line : ""}` }), h("p", { text: c.text }), c.reply ? h("p", { class: "muted", text: "Reply: " + c.reply }) : null)))) : null,
      d.changed.length ? h("section", null, h("h4", { text: "Changed files" }), h("ul", { class: "rows" }, d.changed.map(c => h("li", { class: "mono small", text: `${c.path}  +${c.added} -${c.removed}` })))) : null,
      h("section", null, h("h4", { text: "Change this task" }), taskControls(st, d, seats), editing ? editForm(d) : null),
      d.events.length ? h("section", null, h("h4", { text: "History" }), feed(d.events)) : null));
}

function acceptForm(d, seats) {
  const files = h("input", { type: "text", id: "acc-files", "data-k": "acc-files-" + d.id, value: d.files.join(", "), spellcheck: "false" });
  const proof = h("input", { type: "text", id: "acc-proof", "data-k": "acc-proof-" + d.id, value: d.proof.join(" && "), spellcheck: "false" });
  const owner = h("select", { id: "acc-owner", "data-k": "acc-owner-" + d.id }, h("option", { value: "" }, "Anyone"), seats.map(x => h("option", { value: x.handle }, x.handle)));
  return h("div", { class: "stack" }, h("p", { class: "note", text: d.filed_by && d.filed_by !== "human" ? `${d.filed_by} filed this while working. Accept it as work, or cancel it below.` : "Waiting for files and a test command." }),
    h("div", { class: "field" }, h("label", { for: "acc-files", text: "Files it may change" }), files),
    h("div", { class: "field" }, h("label", { for: "acc-proof", text: "Test command (runs on your computer)" }), proof),
    h("div", { class: "field" }, h("label", { for: "acc-owner", text: "Who does it" }), owner),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => act("task.accept",
      { task: d.id, files: csv(files.value), proof: proof.value.trim() ? proof.value.split("&&").map(x => x.trim()).filter(Boolean) : null, owner: owner.value || null },
      { button: e.currentTarget, title: "Accepted " + d.id }) }, "Accept as work")));
}

function taskControls(st, d, seats) {
  const finished = ["done", "cancelled"].includes(d.status);
  if (finished) return h("p", { class: "faint", text: "Finished tasks cannot be changed." });
  const reviewSel = h("select", { "aria-label": "Review depth for this task", onchange: e => act("task.set_review", { task: d.id, level: e.target.value }) },
    ["default", "low", "mid", "high"].map(v => h("option", { value: v, selected: v === "default" ? true : null }, v === "default" ? `Review: project default` : `Review: ${v}`)));
  const ownerSel = h("select", { "aria-label": "Owner", onchange: e => act("task.reassign", { task: d.id, owner: e.target.value || null }) },
    h("option", { value: "" }, "Owner: anyone"), seats.map(x => h("option", { value: x.handle, selected: x.handle === d.owner ? true : null }, "Owner: " + x.handle)));
  const confirmKey = "cancel-" + d.id;
  const reason = h("input", { type: "text", "data-k": "cancel-task-" + d.id, placeholder: "Why", "aria-label": "Reason for cancelling" });
  return h("div", { class: "stack" },
    h("div", { class: "btn-row" }, ownerSel, reviewSel),
    h("div", { class: "btn-row" },
      h("button", { type: "button", onclick: () => { ui.editOpen = ui.editOpen === d.id ? false : d.id; render(); } }, "Edit details"),
      h("button", { type: "button", onclick: () => { ui.linkOpen = ui.linkOpen === d.id ? false : d.id; render(); } }, icon("link", "sm"), "Link"),
      ui.confirm[confirmKey] ? null : h("button", { class: "danger", type: "button", onclick: () => { ui.confirm[confirmKey] = true; render(); } }, "Cancel task…")),
    ui.linkOpen === d.id ? linkForm(st, d) : null,
    ui.confirm[confirmKey] ? h("div", { class: "btn-row" }, reason, h("button", { class: "danger solid", type: "button", onclick: e => {
      if (!reason.value.trim()) { toast("Add a reason", "The owner reads it."); return; }
      act("task.cancel", { task: d.id, reason: reason.value.trim() }, { button: e.currentTarget, after: () => { ui.confirm[confirmKey] = false; } });
    } }, "Cancel task"), h("button", { type: "button", onclick: () => { ui.confirm[confirmKey] = false; render(); } }, "Keep it")) : null);
}

function linkForm(st, d) {
  const rel = h("select", { "aria-label": "Relation", "data-k": "link-rel" },
    [["waits_for", "waits for"], ["related", "is related to"], ["discovered_from", "was found while doing"], ["parent", "is part of epic"]].map(([v, l]) => h("option", { value: v }, l)));
  const other = h("select", { "aria-label": "Other task", "data-k": "link-other" }, st.tasks.filter(t => t.id !== d.id).map(t => h("option", { value: t.id }, `${t.id} ${fit(t.title, 40)}`)));
  return h("div", { class: "btn-row" }, h("span", { class: "id", text: d.id }), rel, other,
    h("button", { class: "primary", type: "button", onclick: e => act("task.link", { task: d.id, relation: rel.value, other: other.value }, { button: e.currentTarget, after: () => { ui.linkOpen = false; } }) }, "Add link"));
}

function editForm(d) {
  const early = ["backlog", "open", "ready"].includes(d.status);
  const t = h("input", { type: "text", id: "e-title", "data-k": "e-title-" + d.id, value: d.title });
  const p = h("select", { id: "e-prio", "data-k": "e-prio-" + d.id }, [0, 1, 2, 3, 4].map(n => h("option", { value: String(n), selected: n === d.priority ? true : null }, "P" + n)));
  const l = h("input", { type: "text", id: "e-labels", "data-k": "e-labels-" + d.id, value: d.labels.join(", ") });
  const f = h("input", { type: "text", id: "e-files", "data-k": "e-files-" + d.id, value: d.files.join(", "), disabled: !early });
  const c = h("input", { type: "text", id: "e-proof", "data-k": "e-proof-" + d.id, value: d.proof.join(" && "), disabled: !early });
  return h("div", { class: "stack" },
    h("div", { class: "form-grid" },
      h("div", { class: "field wide" }, h("label", { for: "e-title", text: "Title" }), t),
      h("div", { class: "field" }, h("label", { for: "e-prio", text: "Priority" }), p),
      h("div", { class: "field" }, h("label", { for: "e-labels", text: "Labels" }), l),
      h("div", { class: "field wide" }, h("label", { for: "e-files", text: "Files" }), early ? null : h("span", { class: "help", text: "Fixed while work is under way." }), f),
      h("div", { class: "field wide" }, h("label", { for: "e-proof", text: "Test command" }), c)),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => {
      const params = { task: d.id, title: t.value.trim(), priority: Number(p.value), labels: csv(l.value) || [] };
      if (early) { params.files = csv(f.value) || []; params.proof = c.value.trim() ? c.value.split("&&").map(x => x.trim()).filter(Boolean) : []; }
      act("task.edit", params, { button: e.currentTarget, after: () => { ui.editOpen = false; } });
    } }, "Save changes")));
}

/* ---------------------------------------------------------------- reviews */

PAGES.reviews = st => {
  const sel = route.sub && /^T/i.test(route.sub) ? route.sub.toUpperCase() : (st.reviews[0] && st.reviews[0].task) || "";
  const mine = st.reviews;
  const list = mine.length ? h("ul", { class: "rows" }, mine.map(r => h("li", { class: "btn-row" },
    h("a", { class: "id", href: "#/reviews/" + r.task, text: r.task }), h("span", { text: r.title }), chip(r.level + " review", "you")))) :
    h("p", { class: "empty", text: "No review is waiting for you. Models review each other; a review only comes to you when no model from another company can do it." });
  const requests = st.level_requests.length ? panel("Requests for a deeper review", "A model wants a task read more closely than the project's review depth.",
    h("ul", { class: "rows" }, st.level_requests.map(q => h("li", null, h("p", null, h("strong", { text: `${q.seat} asks for a ${q.level} review of ${q.task}` })),
      h("p", { class: "muted", text: q.reason }),
      h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => act("review.level_decide", { id: q.id, decision: "approve" }, { button: e.currentTarget }) }, "Allow"),
        h("button", { type: "button", onclick: e => act("review.level_decide", { id: q.id, decision: "deny" }, { button: e.currentTarget }) }, "Keep current depth")))))) : null;
  const recent = st.tasks.filter(t => t.status === "in_review");
  return h("div", { class: "stack" },
    pageHead("Reviews", `Project review depth: ${st.project.review}. Change it in Settings, or per task on the task's page.`),
    panel("Waiting for you", null, list),
    sel && mine.some(r => r.task === sel) ? reviewBlock(st, sel) : null,
    requests,
    panel("Being reviewed by models", null, recent.length ? h("ul", { class: "rows" }, recent.map(t => h("li", { class: "btn-row" },
      h("a", { class: "id", href: "#/tasks/" + t.id, text: t.id }), h("span", { text: t.title }), h("span", { class: "faint", text: `by ${t.owner}, reviewed by ${(t.reviewers || []).join(", ") || "-"} (${t.review})` })))) :
      h("p", { class: "empty", text: "Nothing is in review right now." })));
};

function reviewBlock(st, id) {
  const d = cache.diff[id];
  if (!d) { getJSON("/api/diff?task=" + encodeURIComponent(id)).then(x => { cache.diff[id] = x; render(); }); return panel("Changes in " + id, "Loading…"); }
  const pts = h("textarea", { id: "rv-points", "data-k": "rv-" + id, rows: "4", placeholder: "One point per line: what is good, what must change" });
  const lines = (d.diff || "").split("\n");
  const diff = d.diff ? h("div", { class: "diff", role: "region", "aria-label": "Changes", tabindex: "0" }, lines.map(l => h("div", {
    class: l.startsWith("diff --git") || l.startsWith("+++") || l.startsWith("---") ? "file" : l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "",
    text: l || " " }))) : h("p", { class: "note", text: d.note || "No changes." });
  const send = verdict => e => {
    const points = pts.value.split("\n").map(x => x.trim()).filter(Boolean);
    if (verdict === "changes" && !points.length) { toast("Say what must change", "Write at least one point; the owner works from it."); pts.focus(); return; }
    act("review.submit", { task: id, verdict, points: points.length ? points : null }, { button: e.currentTarget, after: () => { delete cache.diff[id]; go("#/reviews"); } });
  };
  return panel("Review " + id, "Read the changes, then approve or ask for changes.", diff,
    h("div", { class: "field" }, h("label", { for: "rv-points", text: "Your points" }), pts),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: send("approve") }, icon("check", "sm"), "Approve"),
      h("button", { type: "button", onclick: send("changes") }, "Request changes")));
}

/* ---------------------------------------------------------------- alerts and votes */

const LEVELS = [[1, "Note", "For the record; nobody has to act."], [2, "Heads-up", "Worth knowing for anyone nearby."],
  [3, "Problem", "Affected models must acknowledge before taking new work."], [4, "Blocking", "Holds the affected files until resolved."],
  [5, "Critical", "Freezes the files and tells every model to stop."]];

PAGES.alerts = st => {
  const open = st.alerts;
  const alertList = open.length ? h("ul", { class: "rows" }, open.map(a => h("li", { id: "alert-" + a.id },
    h("p", { class: "inline-list" }, h("span", { class: "level l" + a.level, text: "L" + a.level }), h("strong", { text: a.title }), h("span", { class: "faint", text: `${a.id}, from ${a.by}, ${a.at}` })),
    a.description ? h("p", { class: "pre muted", text: a.description }) : null,
    a.evidence ? h("div", { class: "output", text: a.evidence }) : null,
    a.files.length ? h("p", { class: "mono small", text: "Files: " + a.files.join(", ") }) : null,
    a.must_ack.length ? h("p", { class: "faint", text: `Acknowledged by ${a.acked.join(", ") || "nobody yet"} of ${a.must_ack.join(", ")}` }) : null,
    a.proposed ? h("p", { class: "note warn", text: `${a.proposed_by} suggests level ${a.proposed}.` }) : null,
    alertActions(a)))) : h("p", { class: "empty", text: "No open alerts." });
  const votes = st.votes.length ? h("ul", { class: "rows" }, st.votes.map(v => h("li", null,
    h("p", { class: "inline-list" }, h("strong", { text: v.topic }), chip(v.status === "tied" ? "tied: you decide" : "voting", v.status === "tied" ? "you" : "work")),
    h("ul", { class: "points" }, v.options.map(o => {
      const bs = v.ballots.filter(b => b.choice === o);
      return h("li", null, h("strong", { text: `${o}: ${bs.length}` }), bs.map(b => h("p", { class: "muted small", text: `${b.seat}: ${b.reason}` })));
    })),
    h("div", { class: "btn-row" }, v.options.map(o => h("button", { type: "button", class: v.status === "tied" ? "primary" : "", onclick: e => act("vote.decide", { id: v.id, choice: o }, { button: e.currentTarget }) }, "Decide: " + o)))))) :
    h("p", { class: "empty", text: "No open votes. Models open one when they cannot agree." });
  return h("div", { class: "stack" },
    pageHead("Alerts and votes", "Problems the models raised, from 1 (a note) to 5 (stop everything), and decisions they put to a vote."),
    h("div", { class: "grid-2" }, h("div", { class: "stack" }, panel("Open alerts", null, alertList), panel("Votes", null, votes)), raiseForm()));
};

function alertActions(a) {
  const note = h("input", { type: "text", "data-k": "res-" + a.id, placeholder: "What fixed it", "aria-label": "What fixed it" });
  const lvl = h("select", { "aria-label": "Level", onchange: e => act("alert.set_level", { id: a.id, level: Number(e.target.value) }) },
    LEVELS.map(([n, name]) => h("option", { value: String(n), selected: n === a.level ? true : null }, `Level ${n}: ${name}`)));
  return h("div", { class: "btn-row" }, note, h("button", { class: "primary", type: "button", onclick: e => {
    act("alert.resolve", { id: a.id, resolution: note.value.trim() || "resolved by the human" }, { button: e.currentTarget });
  } }, "Resolve"), lvl);
}

function raiseForm() {
  const lvl = h("select", { id: "al-level", "data-k": "al-level" }, LEVELS.map(([n, name]) => h("option", { value: String(n), selected: n === 3 ? true : null }, `${n}: ${name}`)));
  const lvlHelp = h("span", { class: "help", text: LEVELS[2][2] });
  lvl.addEventListener("change", () => { lvlHelp.textContent = LEVELS[Number(lvl.value) - 1][2]; });
  const title = h("input", { type: "text", id: "al-title", "data-k": "al-title" });
  const desc = h("textarea", { id: "al-desc", "data-k": "al-desc", rows: "3" });
  const files = h("input", { type: "text", id: "al-files", "data-k": "al-files", placeholder: "src/auth/**", spellcheck: "false" });
  return panel("Raise an alert yourself", "Tell every model about a problem, with the files it touches.",
    h("div", { class: "field" }, h("label", { for: "al-level", text: "Level" }), lvl, lvlHelp),
    h("div", { class: "field" }, h("label", { for: "al-title", text: "What is wrong" }), title),
    h("div", { class: "field" }, h("label", { for: "al-desc", text: "Details" }), desc),
    h("div", { class: "field" }, h("label", { for: "al-files", text: "Files it affects" }), files),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => {
      if (!title.value.trim()) { toast("Say what is wrong", ""); title.focus(); return; }
      act("alert.raise", { level: Number(lvl.value), title: title.value.trim(), description: desc.value.trim() || null, files: files.value.trim() || null },
        { button: e.currentTarget, after: () => { title.value = ""; desc.value = ""; files.value = ""; } });
    } }, "Raise alert")));
}

/* ---------------------------------------------------------------- models */

PAGES.models = st => {
  if (route.sub === "add") return h("div", { class: "stack" }, pageHead("Add a model", "Each model works in its own app with your own subscription. No API keys."), addForm(st));
  const sel = route.sub;
  const rows = st.seats.length ? h("ul", { class: "rows" }, st.seats.map(x => seatRow(st, x, x.handle === sel))) :
    h("div", { class: "empty" }, h("strong", { text: "No models yet." }), "Add two or more, ideally from different companies, so they check each other's work.");
  return h("div", { class: "stack" },
    pageHead("Models", "Who sits at the table, where each one works, and how to start it.",
      h("button", { class: "primary", type: "button", onclick: () => go("#/models/add") }, icon("plus", "sm"), "Add a model")),
    panel(null, null, rows), connectPanel(st));
};

function seatRow(st, x, highlight) {
  const [cls, note] = seatState(x);
  const tone = { live: "ok", working: "work", idle: "idle", paused: "idle" }[cls];
  const started = ui.started[x.handle];
  const start = x.start;
  const startBtn = x.status !== "active" ? null : start.kind === "terminal"
    ? h("button", { class: x.live ? "" : "primary", type: "button", disabled: x.live ? true : null, title: x.live ? "Already at the table" : null, onclick: e => startSeat(x, e.currentTarget) }, icon("terminal", "sm"), x.live ? "Running" : "Start in a terminal")
    : start.kind === "vscode" ? h("button", { class: "primary", type: "button", onclick: e => startSeat(x, e.currentTarget) }, icon("code", "sm"), "Open in VS Code")
      : start.kind === "editor" ? h("button", { class: "primary", type: "button", onclick: e => startSeat(x, e.currentTarget) }, icon("code", "sm"), "Open in " + x.app_label.replace(" editor", ""))
        : h("button", { type: "button", onclick: () => { ui.started[x.handle] = { steps: start.steps, join: start.join }; render(); } }, "Show how to start it");
  const more = [];
  if (x.status === "paused") more.push(h("button", { type: "button", onclick: e => act("seat.resume", { handle: x.handle }, { button: e.currentTarget }) }, "Resume"));
  else more.push(h("button", { class: "quiet", type: "button", onclick: e => act("seat.pause", { handle: x.handle }, { button: e.currentTarget }) }, "Pause"));
  if (x.live) more.push(h("button", { class: "quiet", type: "button", title: "Use this if you closed its chat window", onclick: e => act("seat.release", { handle: x.handle }, { button: e.currentTarget }) }, "Free the seat"));
  const rmKey = "rm-" + x.handle;
  more.push(ui.confirm[rmKey]
    ? h("button", { class: "danger solid", type: "button", onclick: e => act("seat.remove", { handle: x.handle }, { button: e.currentTarget, after: () => { ui.confirm[rmKey] = false; } }) }, "Remove " + x.handle)
    : h("button", { class: "quiet", type: "button", onclick: () => { ui.confirm[rmKey] = true; render(); setTimeout(() => { ui.confirm[rmKey] = false; render(); }, 5000); } }, "Remove…"));
  return h("li", { class: highlight ? "highlight" : "", id: "seat-" + x.handle },
    h("div", { class: "grid-split" },
      h("div", null,
        h("p", { class: "inline-list" }, h("strong", { text: x.handle }), chip(x.status === "paused" ? "paused" : cls === "live" ? "at the table" : cls === "working" ? "working" : note, tone)),
        h("p", { class: "muted small", text: `${x.model}, ${x.company}, ${x.app_label}` }),
        h("p", { class: "faint", text: `Roles: ${x.roles.join(", ")}` + (x.tasks.length ? `. Working on ${x.tasks.join(", ")}` : "") + (x.doing ? `. ${x.doing}` : "") }),
        x.worktree ? h("p", { class: "faint" }, "Works in ", h("span", { class: "mono", text: x.worktree })) : null),
      h("div", { class: "stack" }, h("div", { class: "btn-row" }, startBtn, more),
        started ? startedBox(x, started) : null)));
}

async function startSeat(x, btn) {
  const res = await special("start", { handle: x.handle }, { button: btn, silent: true });
  if (res.ok) { ui.started[x.handle] = { text: res.text, join: res.join, steps: res.steps }; toast(capital(res.text), x.start.kind === "terminal" ? "Approve the roundtable tools when the app asks." : ""); }
  else { ui.started[x.handle] = { error: res.message, hint: res.hint, command: res.command, folder: res.folder, join: x.start.join, steps: x.start.steps }; toast(res.message || "Could not start it", res.hint || "", { error: true }); }
  render();
}

function startedBox(x, info) {
  return h("div", { class: "note" + (info.error ? " warn" : "") },
    info.error ? h("p", null, h("strong", { text: info.error })) : null,
    info.command ? [h("p", { class: "small", text: "Run this in a terminal instead:" }), copyBox(`cd ${info.folder || ""} && ${info.command}`.replace(/^cd  && /, ""))] : null,
    info.steps && info.steps.length ? h("ol", { class: "points" }, info.steps.map(s => h("li", { text: s }))) : null,
    info.join ? [h("p", { class: "small", text: "Message to send in its chat:" }), copyBox(info.join)] : null);
}

function addForm(st) {
  const appSel = h("select", { id: "m-app", "data-k": "m-app" });
  const groups = [["terminal", "In a terminal"], ["vscode", "In an editor"], ["editor", null], ["desktop", "Desktop apps"], ["manual", "Other"]];
  const groupEls = {};
  groups.forEach(([k, label]) => { if (label) { groupEls[k] = h("optgroup", { label }); appSel.append(groupEls[k]); } });
  st.apps.forEach(a => (groupEls[a.start] || groupEls.vscode).append(h("option", { value: a.key }, a.label)));
  const name = h("input", { type: "text", id: "m-name", "data-k": "m-name", placeholder: "opus", autocomplete: "off", spellcheck: "false" });
  const model = h("input", { type: "text", id: "m-model", "data-k": "m-model", list: "m-models", autocomplete: "off", spellcheck: "false" });
  const dl = h("datalist", { id: "m-models" });
  const company = h("select", { id: "m-company", "data-k": "m-company" }, h("option", { value: "" }, "Work it out from the app or model"), st.companies.map(c => h("option", { value: c }, c)));
  const roles = ["plan", "build", "review"].map(r => h("input", { type: "checkbox", value: r, checked: true, "data-k": "m-role-" + r, class: "m-role" }));
  const help = h("p", { class: "note small" });
  const update = () => {
    const a = st.apps.find(x => x.key === appSel.value) || st.apps[0];
    dl.replaceChildren(...((st.models[a.company] || Object.values(st.models).flat()).map(m => h("option", { value: m }))));
    if (!model.value && st.models[a.company] && st.models[a.company][0]) model.placeholder = st.models[a.company][0];
    roles[1].disabled = !a.coding;
    if (!a.coding) roles[1].checked = false;
    help.textContent = {
      terminal: "Roundtable gives it its own working copy and opens it in a terminal for you, already joined to the table.",
      vscode: "Roundtable gives it its own working copy. You open that folder in VS Code and send one message to join.",
      editor: "Roundtable gives it its own working copy with the connection already set. Open that folder in the editor and send one message to join.",
      desktop: a.coding ? "Connect the app once (below the model list), open the model's folder in it, and send one message to join." : "This app cannot edit files, so it plans and reviews. Connect it once and send one message to join.",
      manual: "You add Roundtable to the app's MCP settings yourself; the model's page shows exactly what to enter.",
    }[a.start] || "";
  };
  appSel.addEventListener("change", update);
  setTimeout(update, 0);
  return panel(null, null,
    h("div", { class: "form-grid" },
      h("div", { class: "field" }, h("label", { for: "m-name", text: "Name at the table" }), h("span", { class: "help", text: "Short and lowercase, like opus or sol. It is how the models address each other." }), name),
      h("div", { class: "field" }, h("label", { for: "m-app", text: "Where it runs" }), appSel),
      h("div", { class: "field" }, h("label", { for: "m-model", text: "Model" }), h("span", { class: "help", text: "The name the app uses. In Codex, /model shows it; in Claude Code, /model." }), model, dl),
      h("div", { class: "field" }, h("label", { for: "m-company", text: "Made by" }), h("span", { class: "help", text: "Reviews go to a model from a different company when there is one." }), company),
      h("fieldset", { class: "field wide" }, h("legend", { text: "What it does" }), h("div", { class: "btn-row" },
        h("label", { class: "check" }, roles[0], h("span", null, "Plans")), h("label", { class: "check" }, roles[1], h("span", null, "Builds")), h("label", { class: "check" }, roles[2], h("span", null, "Reviews")))),
      h("div", { class: "wide" }, help)),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => {
      const handle = name.value.trim().toLowerCase();
      const m = model.value.trim() || model.placeholder;
      if (!handle) { toast("Give it a name", "For example opus or sol."); name.focus(); return; }
      if (!m) { toast("Which model?", "Type the model name the app uses."); model.focus(); return; }
      act("seat.add", { handle, model: m, app: appSel.value, company: company.value || null, roles: roles.filter(r => r.checked).map(r => r.value) },
        { button: e.currentTarget, title: "Added " + handle, after: () => go("#/models/" + handle) });
    } }, "Add model"), h("button", { type: "button", onclick: () => go("#/models") }, "Cancel")));
}

function connectPanel(st) {
  const c = st.project.connected;
  const items = [
    ["claude-code", "Claude Code (project settings)", "Only needed if you open Claude Code yourself instead of using Start. Writes .mcp.json in the project folder."],
    ["claude-app", "Claude desktop app", "Lets a Claude desktop chat join. Restart the app afterwards."],
    ["codex", "Codex: terminal, VS Code and the ChatGPT app", "One entry in ~/.codex/config.toml serves all three. Restart them afterwards."],
    ["copilot", "GitHub Copilot CLI", "Adds Roundtable to ~/.copilot/mcp-config.json."],
  ];
  return panel("Connect apps", "Models you start from this page are connected automatically. These are for apps you open yourself. Roundtable merges its entry into each settings file and keeps a backup.",
    h("ul", { class: "rows" }, items.map(([key, label, help]) => h("li", null,
      h("p", { class: "inline-list" }, h("strong", { text: label }), c[key] ? chip("connected", "ok") : chip("not connected", "idle")),
      h("p", { class: "faint", text: help }),
      ui.preview[key] ? h("div", { class: "output", text: ui.preview[key] }) : null,
      h("div", { class: "btn-row" },
        h("button", { type: "button", onclick: async e => { const r = await special("connect", { app: key, preview: true }, { button: e.currentTarget, silent: true }); ui.preview[key] = r.ok ? r.text : (r.message + (r.hint ? "\n" + r.hint : "")); render(); } }, "Preview the change"),
        h("button", { class: c[key] ? "" : "primary", type: "button", onclick: e => special("connect", { app: key }, { button: e.currentTarget, title: "Connected", after: () => { delete ui.preview[key]; } }) }, c[key] ? "Update" : "Connect"),
        c[key] ? h("button", { class: "quiet", type: "button", onclick: e => special("connect", { app: key, remove: true }, { button: e.currentTarget, title: "Disconnected" }) }, "Disconnect") : null)))));
}

/* ---------------------------------------------------------------- usage */

PAGES.usage = st => {
  const warn = (st.config.find(c => c.key === "usage.warn_percent") || { value: 90 }).value;
  return h("div", { class: "stack" },
    pageHead("Usage", "Each model's context and plan limits, from its own app, and what the conversation between models cost."),
    st.seats.length ? h("div", { class: "seat-usage" }, st.seats.map(x => usageCard(x, warn))) : panel(null, null, h("p", { class: "empty", text: "Add models to see their usage." })),
    panel("Where these numbers come from", null, h("div", { class: "prose small" },
      h("p", { text: "Claude Code started from Roundtable reports context, session tokens and the 5-hour and 7-day limits through its status line. Codex (terminal, VS Code and ChatGPT app) writes them to its session logs, which Roundtable reads. Other apps do not share this, so only Roundtable's own exchange is shown for them." }),
      h("p", { text: `Roundtable's tool definitions cost about ${num(st.overhead_tokens)} tokens once per chat session. Exchange tokens are estimated from characters (about 4 per token).` }))));
};

function meter(label, pct, sub, warnAt) {
  if (pct === null || pct === undefined) return h("div", { class: "meter none" }, h("span", { text: label }), h("div", { class: "bar" }), h("span", { class: "val", text: "-" }));
  const v = Math.max(0, Math.min(100, Number(pct)));
  const fill = h("div", { class: "fill" + (v >= warnAt ? " stop" : v >= warnAt * 0.75 ? " warn" : "") });
  fill.style.width = v + "%";
  return h("div", { class: "meter", title: sub || null }, h("span", { text: label }), h("div", { class: "bar", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(v)), "aria-label": label }, fill),
    h("span", { class: "val", text: Math.round(v) + "%" }));
}

function resets(epoch) {
  if (!epoch) return "";
  const mins = Math.round((Number(epoch) * 1000 - Date.now()) / 60000);
  if (mins <= 0) return "resetting now";
  return mins < 90 ? `resets in ${mins} min` : mins < 2880 ? `resets in ${Math.round(mins / 60)} h` : `resets in ${Math.round(mins / 1440)} days`;
}

function usageCard(x, warnAt) {
  const u = x.usage, snap = u.snapshot || {}, ex = u.exchange;
  return h("section", { class: "panel" }, h("header", null, h("div", null, h("h2", { text: x.handle }), h("p", { text: `${x.model}, ${x.app_label}` }))),
    h("div", { class: "panel-body stack" },
      u.snapshot ? h("div", null,
        meter("Context", snap.context_pct, snap.context_size ? `of ${Math.round(snap.context_size / 1000)}k tokens` : "", warnAt),
        meter("5 hours", snap.limit_5h && snap.limit_5h.pct, snap.limit_5h && resets(snap.limit_5h.resets_at), warnAt),
        meter("7 days", snap.limit_7d && snap.limit_7d.pct, snap.limit_7d && resets(snap.limit_7d.resets_at), warnAt))
        : h("p", { class: "no-data", text: ["claude-code", "codex-cli", "codex-vscode", "codex-app"].includes(x.app)
          ? "No numbers yet. They appear after its first reply" + (x.app === "claude-code" ? " when it is started from Roundtable." : ".")
          : "This app does not share its context or plan limits." }),
      h("dl", { class: "kv" },
        h("dt", { text: "Session" }), h("dd", { text: snap.session_tokens ? num(snap.session_tokens) + " tokens" : "not reported by this app" }),
        snap.limit_5h ? [h("dt", { text: "5-hour limit" }), h("dd", { text: resets(snap.limit_5h.resets_at) || "-" })] : null,
        snap.limit_7d ? [h("dt", { text: "7-day limit" }), h("dd", { text: resets(snap.limit_7d.resets_at) || "-" })] : null,
        h("dt", { text: "Roundtable" }), h("dd", { text: `${num(ex.calls)} calls, about ${num(ex.tokens)} tokens (${num(ex.tokens_today)} today)` }))));
}

/* ---------------------------------------------------------------- memory */

PAGES.memory = st => {
  const text = h("textarea", { id: "mem-text", "data-k": "mem-text", rows: "3", placeholder: "Tests need DATABASE_URL set; use the sqlite one in tests/.env" });
  const tags = h("input", { type: "text", id: "mem-tags", "data-k": "mem-tags", placeholder: "tests" });
  const list = st.memories.length ? h("ul", { class: "rows" }, st.memories.map(m => h("li", null,
    h("p", { class: "inline-list" }, m.pinned ? chip("pinned", "you") : null, h("span", { class: "id", text: m.id }), h("span", { class: "faint", text: `${m.author === "human" ? "you" : m.author}, ${m.at}` }), m.tags.map(t => h("span", { class: "tag", text: t }))),
    h("p", { class: "pre", text: m.text }),
    h("div", { class: "btn-row" },
      h("button", { class: "quiet", type: "button", onclick: e => act("memory.pin", { id: m.id, pinned: !m.pinned }, { button: e.currentTarget }) }, icon("pin", "sm"), m.pinned ? "Unpin" : "Pin"),
      h("button", { class: "quiet", type: "button", onclick: e => act("memory.forget", { id: m.id, reason: "removed from the dashboard" }, { button: e.currentTarget }) }, "Forget"))))) :
    h("p", { class: "empty", text: "Nothing remembered yet. Models add notes as they learn things about the project; you can too." });
  return h("div", { class: "stack" },
    pageHead("Memory", "Short notes that outlive chats. Every model sees the pinned ones and the newest others when it joins, so a fresh chat starts with what earlier ones learned."),
    h("div", { class: "grid-2" }, panel("Remembered", `${plural(st.memories.length, "note")}. Notes written by models are shown to other models as information, never as instructions.`, list),
      panel("Add a note", "Your notes are pinned.",
        h("div", { class: "field" }, h("label", { for: "mem-text", text: "Note (60 words at most)" }), text),
        h("div", { class: "field" }, h("label", { for: "mem-tags", text: "Tags" }), tags),
        h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => {
          if (!text.value.trim()) { toast("Write the note first", ""); text.focus(); return; }
          act("memory.add", { text: text.value.trim(), tags: csv(tags.value) }, { button: e.currentTarget, after: () => { text.value = ""; tags.value = ""; } });
        } }, "Remember")))));
};

/* ---------------------------------------------------------------- activity */

PAGES.activity = st => {
  const q = h("input", { type: "search", "data-k": "act-q", placeholder: "Search the history", "aria-label": "Search the history" });
  const task = h("input", { type: "text", "data-k": "act-task", placeholder: "Task, like T3", "aria-label": "Only this task", spellcheck: "false" });
  const key = (cache.logKey || "");
  const events = cache.log && key ? cache.log : st.events;
  const run = async more => {
    const params = new URLSearchParams();
    if (q.value.trim()) params.set("q", q.value.trim());
    if (task.value.trim()) params.set("task", task.value.trim());
    if (more && events.length) params.set("before", events[events.length - 1].id);
    const res = await getJSON("/api/log?" + params);
    cache.log = more ? events.concat(res.events || []) : (res.events || []);
    cache.logKey = params.toString() || "all";
    render();
  };
  return h("div", { class: "stack" },
    pageHead("Activity", "Everything that happened, newest first. Models read the same history as short digests, so this costs them nothing."),
    panel(null, null, h("form", { class: "toolbar", onsubmit: e => { e.preventDefault(); run(false); } }, q, task,
      h("button", { type: "submit" }, icon("search", "sm"), "Search"),
      key ? h("button", { class: "quiet", type: "button", onclick: () => { cache.log = null; cache.logKey = ""; render(); } }, "Clear") : null),
      feed(events),
      events.length >= 80 ? h("div", { class: "btn-row" }, h("button", { type: "button", onclick: () => run(true) }, "Show older")) : null));
};

/* ---------------------------------------------------------------- settings */

const MAIN_SECTIONS = ["review", "proof", "git", "watch", "usage", "project"];
const SECTION_LABEL = { project: "Project", review: "Reviews", leases: "File leases", seats: "Models", proof: "Tests", planning: "Planning", limits: "Limits",
  git: "Git", watch: "Notifications", usage: "Usage", dashboard: "Dashboard", history: "History" };

PAGES.settings = st => {
  const sections = {};
  st.config.forEach(c => (sections[c.section] = sections[c.section] || []).push(c));
  const doc = cache.doctor;
  return h("div", { class: "stack" },
    pageHead("Settings", "Changes apply at once and are saved in .roundtable/config.toml. Models cannot change these."),
    h("div", { class: "grid-2" },
      h("div", { class: "stack" }, Object.entries(sections).filter(([sec]) => MAIN_SECTIONS.includes(sec)).map(([sec, items]) => panel(SECTION_LABEL[sec] || sec, null, items.map(settingRow))),
        h("details", { class: "more-settings", "data-k": "more-settings" }, h("summary", null, icon("chevron", "sm turn"), "More settings: limits, planning, leases, history"),
          h("div", { class: "stack" }, Object.entries(sections).filter(([sec]) => !MAIN_SECTIONS.includes(sec)).map(([sec, items]) => panel(SECTION_LABEL[sec] || sec, null, items.map(settingRow)))))),
      h("div", { class: "stack" },
        panel("Check the setup", "Looks at git, the models' working copies, app connections and the commit guard.",
          h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: async e => { busy(e.currentTarget, true); cache.doctor = await getJSON("/api/doctor"); busy(e.currentTarget, false); render(); } }, doc ? "Check again" : "Run the checks")),
          doc ? h("ul", { class: "rows" }, doc.items.map(it => h("li", null, h("p", { class: "inline-list" }, chip(it.status === "ok" ? "ok" : it.status === "warn" ? "check" : "problem", it.status === "ok" ? "ok" : it.status === "warn" ? "warn" : "stop"), h("span", { text: it.message })),
            it.fix ? h("p", { class: "faint" }, "Fix: ", h("span", { class: "mono", text: it.fix })) : null))) : null),
        panel("Housekeeping", null,
          h("p", { class: "faint", text: "Compacting keeps each finished task's outcome and drops step-by-step detail older than the History setting." }),
          h("div", { class: "btn-row" }, h("button", { type: "button", onclick: e => act("admin.compact", {}, { button: e.currentTarget }) }, "Compact old history"),
            h("button", { type: "button", onclick: e => act("admin.export", {}, { button: e.currentTarget }) }, "Export a snapshot"))))));
};

function settingRow(c) {
  const id = "cfg-" + c.key.replace(".", "-");
  const save = v => act("admin.config_set", { key: c.key, value: v }, { title: "Saved" });
  let control;
  if (c.type === "switch") control = h("input", { type: "checkbox", id, checked: c.value, onchange: e => save(e.target.checked ? "true" : "false") });
  else if (c.type === "choice") control = h("select", { id, onchange: e => save(e.target.value) }, c.choices.map(o => h("option", { value: o, selected: o === c.value ? true : null }, o)));
  else if (c.type === "number") control = h("input", { type: "number", id, "data-k": id, min: "0", value: String(c.value), onchange: e => save(e.target.value) });
  else if (c.type === "list") control = h("input", { type: "text", id, "data-k": id, value: (c.value || []).join(", "), onchange: e => save(JSON.stringify(csv(e.target.value) || [])) });
  else control = h("input", { type: "text", id, "data-k": id, value: c.value, onchange: e => save(e.target.value) });
  const name = c.key.split(".")[1].replace(/_/g, " ");
  return c.type === "switch"
    ? h("div", { class: "field" }, h("label", { class: "check", for: id }, control, h("span", null, capital(name), h("small", { text: c.desc }))))
    : h("div", { class: "field" }, h("label", { for: id, text: capital(name) }), h("span", { class: "help", text: c.desc }), control);
}

/* ---------------------------------------------------------------- guide */

PAGES.guide = st => h("div", { class: "stack" },
  pageHead("Guide", "How Roundtable works, in plain words, and the terminal command for everything on these pages."),
  h("div", { class: "grid-2" },
    h("div", { class: "stack" },
      panel("How it works", null, h("div", { class: "prose" },
        h("p", { text: "Several AI models work on one project together. Each one runs in its own app (Claude Code, Codex, VS Code, a desktop app) with your own subscription, and they coordinate through Roundtable instead of talking in one chat." }),
        h("ol", { class: "steps" }, [
          ["Add the models", "On Models. Two or more, ideally from different companies, so they check each other."],
          ["Start each one", "Start opens a terminal or VS Code in the model's own working copy, already connected."],
          ["Give them a goal", "On Plan. Each model writes its own plan without seeing the others, then critiques the others' plans without knowing who wrote them. A chair merges the best parts and the others approve."],
          ["Lock the plan", "You read the tasks and the test commands they will run, and lock it. Nothing runs before you do."],
          ["They build, test and review", "Each task's files are leased to one model. When it says done, Roundtable runs the tests itself. Then a model from another company reviews it, and it is merged into your branch."],
        ].map(([t, d]) => h("li", null, h("div", null, h("strong", { text: t }), h("small", { text: d }))))),
        h("p", { text: "Models do not listen in the background: when a chat goes quiet, type \"check roundtable\" in it. Running rt watch sends you notifications when something needs you." }))),
      panel("Words you will see", null, h("dl", { class: "kv" }, [
        ["Model, or seat", "One model in one app, with a short name like opus. The terminal commands call it a seat."],
        ["Working copy", "A separate folder per coding model, next to your project, on its own git branch. Your folder is never edited by the models."],
        ["Lease", "A task's files belong to the model working on it. Others may read them and send suggestions, not edit."],
        ["Test command (proof)", "The command that shows a task works. Roundtable runs it; a checked box is not enough."],
        ["Review depth", "Low: no code review. Mid: a model from another company reads a map of the changes and the full code of 1 task in 5. High: two models read every line."],
        ["Backlog", "Work a model found while doing something else. It waits for your yes."],
        ["Memory", "Short notes every model sees when it joins, so new chats start informed."],
        ["Alert levels", "1 note, 2 heads-up, 3 must acknowledge, 4 holds the files, 5 stops everyone on those files."],
      ].map(([t, d]) => [h("dt", { text: t }), h("dd", { text: d })])))),
    h("div", { class: "stack" },
      panel("The same things from a terminal", "Every page here has a command. Run them in the project folder.", h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", null, h("tr", null, h("th", { text: "To" }), h("th", { text: "Run" }))),
        h("tbody", null, [
          ["Open this dashboard", "rt ui"], ["See what needs you", "rt status"], ["Add a model", "rt seat add opus --model claude-opus-5-5 --app claude-code"],
          ["Start a model", "rt launch opus"], ["Connect an app you open yourself", "rt setup codex"], ["Give a goal", "rt goal \"what to build\" --review mid"],
          ["Read and lock the plan", "rt plan view, then rt plan lock"], ["List tasks", "rt task list"], ["Accept a backlog item", "rt task accept T7"],
          ["Review when asked", "rt review get T3, then rt review submit T3 approve"], ["Raise an alert", "rt alert raise 3 \"what is wrong\""],
          ["Stop every model", "rt freeze"], ["Usage and limits", "rt usage"], ["Remember something", "rt memory add \"note\""],
          ["Check the setup", "rt doctor"], ["Notifications", "rt watch"],
        ].map(([a, b]) => h("tr", null, h("td", { text: a }), h("td", { class: "mono small", text: b }))))))),
      panel("Where things are", null, h("dl", { class: "kv" },
        h("dt", { text: "Project" }), h("dd", { class: "mono", text: st.project.root }),
        h("dt", { text: "Roundtable's data" }), h("dd", { class: "mono", text: st.project.home }),
        h("dt", { text: "Working copies" }), h("dd", { class: "mono pre", text: st.seats.filter(x => x.worktree).map(x => x.worktree).join("\n") || "none yet" }))),
      panel("Credits", null, h("p", { class: "prose small", text: "Planning together borrows from Andrej Karpathy's LLM Council (anonymous peer review and a chairman). Task tracking learns from Steve Yegge's Beads and Gas Town, and messaging from MCP Agent Mail." })))));

/* ---------------------------------------------------------------- boot */

applyTheme();
window.addEventListener("hashchange", () => { route = parseRoute(); navOpen = false; if (route.page === "tasks" && /^T/i.test(route.sub)) loadTask(route.sub).then(render); render(); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && navOpen) { navOpen = false; render(); } });
refresh(true);
setInterval(() => { if (document.visibilityState === "visible") refresh(false); }, 3000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(false); });
