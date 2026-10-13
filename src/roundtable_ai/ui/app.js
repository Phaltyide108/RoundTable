/* Roundtable dashboard. No framework, no build step: plain DOM, polled state.
   Everything shown comes from /api/state; every change goes through /api/action
   (a Roundtable operation, as the human) or /api/do (set up, start, connect).

   Five places: Home (what is happening, what to do next), Inbox (every decision),
   Team, Plan, Work. Usage, Notes, History, Settings and Help sit under More. */
"use strict";

const TOKEN = document.querySelector('meta[name="rt-token"]').content;
const APP = document.getElementById("app");
const TOASTS = document.getElementById("toasts");

let S = null;            // last state from the server
let lastJSON = "";
let route = { page: "home", parts: [], sub: "" };   // set at boot
const cache = { task: {}, diff: {}, doctor: null, log: null, logKey: "" };
const ui = {
  workSearch: "", showCancelled: false, showAllDone: false, fileOpen: false, linkOpen: false, editOpen: false,
  started: {}, preview: {}, cancelPlan: false, confirm: {}, help: {}, inboxFilter: "all", accepting: {},
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
function capital(t) { t = String(t || ""); return t.charAt(0).toUpperCase() + t.slice(1); }
function fit(t, n) { t = String(t || ""); return t.length > n ? t.slice(0, n - 1) + "…" : t; }
function csv(v) { const out = String(v || "").split(",").map(x => x.trim()).filter(Boolean); return out.length ? out : null; }
function cmds(v) { return String(v || "").split("&&").map(x => x.trim()).filter(Boolean); }
function monogram(handle) { const c = handle.replace(/[^a-z0-9]/gi, ""); return (c.charAt(0).toUpperCase() + (c.charAt(1) || "")).slice(0, 2); }
function who(name) { return name === "human" ? "you" : name === "system" ? "Roundtable" : name; }
function listWords(xs) { return xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1]; }

const PRIORITY = ["Urgent", "High", "Normal", "Low", "Someday"];
const CHECKING = { low: "Light", mid: "Standard", high: "Thorough" };
const CHECKING_TEXT = {
  low: "Tests must pass. No AI reads another's code. Fastest and cheapest.",
  mid: "An AI from another company skims every change, and reads 1 task in 5 (and every risky one) in full.",
  high: "Two AIs read every line and leave comments that must be answered. Slowest; several times the tokens.",
};
const TASK_TONE = { backlog: "you", open: "idle", ready: "idle", claimed: "work", changes_requested: "warn", proving: "work",
  in_review: "work", merge_blocked: "warn", done: "ok", cancelled: "idle" };
const ACTIVE = ["claimed", "changes_requested", "proving", "in_review", "merge_blocked"];
const isLivePlan = p => p && !["done", "cancelled"].includes(p.stage);

/* Event texts are written for models; say them the way a person would. */
function plainText(t) {
  return String(t || "")
    .replace(/\bby the human\b/g, "by you").replace(/\bthe human\b/g, "you")
    .replace(/\s*\(PR\d+\)/g, "")
    .replace(/review depth (low|mid|high)/g, (m, l) => ({ low: "light", mid: "standard", high: "thorough" }[l]) + " checking")
    .replace(/no review, the passed (proof|tests) is the gate/, "no AI reads the code; passing tests is enough")
    .replace(/\bproofs?\b/g, "tests").replace(/\bProofs?\b/g, "Tests")
    .replace(/^checkpoint: /, "progress: ")
    .replace(/^claimed \S+: /, "started ")
    .replace(/^filed \S+ \[[^\]]*\]: /, "found new work: ")
    .replace(/^remembered \S+: /, "noted: ")
    .replace(/^A\d+ L\d (\w+): /, (m, w) => `reported a ${w.toLowerCase()}: `)
    .replace(/\blocked\b/g, "approved").replace(/\block\b/g, "approve").replace(/\bbacklog\b/g, "inbox")
    .replace(/\bseats?\b/g, m => m === "seat" ? "AI" : "AIs");
}

/* ---------------------------------------------------------------- routes */

const ALIAS = { overview: "home", tasks: "work", reviews: "inbox", alerts: "inbox", models: "team", memory: "notes", activity: "history", guide: "help" };

function parseRoute() {
  const parts = (location.hash || "#/home").replace(/^#\/?/, "").split("/").filter(Boolean).map(x => decodeURIComponent(x));
  let page = parts[0] || "home";
  let rest = parts.slice(1);
  if (page === "reviews" && rest[0]) rest = ["review", rest[0]];          // old links: #/reviews/T3
  else if (page === "tasks" && rest[0] === "backlog") { page = "inbox"; rest = []; }   // old links: #/tasks/backlog
  else if (page === "alerts") rest = [];
  page = ALIAS[page] || page;
  return { page, parts: rest, sub: rest[0] || "" };
}
function go(hash) { if (location.hash === hash) render(); else location.hash = hash; }

/* ---------------------------------------------------------------- toasts and server calls */

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
    const first = plainText((res.text || "").split("\n")[0]);
    toast(okTitle || "Done", okTitle ? first : plainText((res.text || "").split("\n").slice(1).join("\n")));
    return true;
  }
  const cmd = res.command || (res.data && res.data.command);
  toast(plainText(res.message) || "That did not work", plainText(res.hint || ""), { error: true, copy: cmd || null });
  return false;
}

async function act(op, params, opts) {
  opts = opts || {};
  busy(opts.button, true);
  const res = await post("/api/action", { op, params: params || {} });
  busy(opts.button, false);
  const ok = showResult(res, opts.title || capital(plainText((res.text || "Done").split("\n")[0])));
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

function taskRoute() { return route.page === "work" && /^T\d/i.test(route.sub) ? route.sub.toUpperCase() : ""; }

async function refresh(force) {
  let next;
  try { next = await getJSON("/api/state"); }
  catch (e) { if (S) toast("Lost contact with the dashboard", "Start it again with: rt ui", { error: true }); return; }
  if (taskRoute()) await loadTask(taskRoute());
  const json = JSON.stringify(next) + JSON.stringify(cache.task[taskRoute()] || null);
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
    if (el.tagName === "DETAILS") { out.open[el.dataset.k] = el.open; return; }
    out.fields[el.dataset.k] = el.type === "checkbox" || el.type === "radio" ? { checked: el.checked } : { value: el.value };
  });
  const a = document.activeElement;
  if (a && a.dataset && a.dataset.k) out.focus = { k: a.dataset.k, start: a.selectionStart, end: a.selectionEnd };
  else if (a && a.dataset && a.dataset.f) out.focus = { f: a.dataset.f };
  return out;
}

function restore(snap, samePage) {
  if (!samePage) return;
  APP.querySelectorAll("[data-k]").forEach(el => {
    if (el.tagName === "DETAILS") { if (el.dataset.k in snap.open) el.open = snap.open[el.dataset.k]; return; }
    const f = snap.fields[el.dataset.k];
    if (!f) return;
    if ("checked" in f) el.checked = f.checked; else el.value = f.value;
  });
  if (snap.focus) {
    const el = snap.focus.k ? APP.querySelector(`[data-k="${CSS.escape(snap.focus.k)}"]`) : APP.querySelector(`[data-f="${CSS.escape(snap.focus.f)}"]`);
    if (el) { el.focus({ preventScroll: true }); try { if (snap.focus.start != null) el.setSelectionRange(snap.focus.start, snap.focus.end); } catch (e) { /* not a text field */ } }
  }
  window.scrollTo(0, snap.scroll);
}

let renderedKey = "";
function render() {
  if (!S) return;
  const key = S.mode + ":" + route.page + ":" + route.parts.join("/");
  const snap = snapshot();
  const same = key === renderedKey;
  renderedKey = key;
  APP.replaceChildren(S.mode === "setup" ? setupScreen(S) : shell());
  restore(snap, same);
  if (!same) {
    window.scrollTo(0, 0);
    const h1 = APP.querySelector("h1");
    if (h1) { h1.setAttribute("tabindex", "-1"); if (document.activeElement === document.body || !APP.contains(document.activeElement)) h1.focus({ preventScroll: true }); }
  }
}

/* ---------------------------------------------------------------- shell */

const NAV_MAIN = [["home", "Home", "home"], ["inbox", "Inbox", "inbox"], ["team", "Team", "models"], ["plan", "Plan", "plan"], ["work", "Work", "work"]];
const NAV_MORE = [
  ["usage", "Usage", "usage", "How much of each AI's limits is used"],
  ["notes", "Notes", "memory", "Things every AI should know about this project"],
  ["history", "History", "activity", "Everything that happened, with search"],
  ["settings", "Settings", "settings", "How Roundtable behaves, and a setup check"],
  ["help", "Help", "guide", "How it works, in plain words"],
];
const MORE_PAGES = NAV_MORE.map(x => x[0]).concat(["more", "switch"]);

const PAGES = {};

function shell() {
  const p = S.project;
  const page = PAGES[route.page] ? route.page : "home";
  const waiting = inboxItems(S).filter(i => i.needs).length;
  const link = ([id, label, ic], cls) => {
    const current = id === page || (id === "more" && MORE_PAGES.includes(page));
    return h("a", { class: cls, href: "#/" + id, "aria-current": current ? "page" : null },
      icon(ic), h("span", { class: "label", text: label }),
      id === "inbox" && waiting ? h("span", { class: "count", "aria-label": `, ${waiting} waiting` }, waiting) : null);
  };
  const theme = store("rt.theme") || "auto";
  const rail = h("aside", { class: "rail", "aria-label": "Roundtable" },
    h("div", { class: "brand" }, h("img", { src: "/icon.svg", alt: "" }), h("span", { text: "Roundtable" })),
    h("button", { class: "project-switch", type: "button", onclick: () => go("#/switch"), title: "Open another project" },
      h("span", { class: "eyebrow", text: "Project" }), h("strong", { text: p.name }), h("small", { text: p.root })),
    h("nav", { "aria-label": "Main" }, h("ul", { class: "nav" }, NAV_MAIN.map(item => h("li", null, link(item))))),
    h("nav", { "aria-label": "More" }, h("p", { class: "nav-head", text: "More" }),
      h("ul", { class: "nav nav-more" }, NAV_MORE.map(item => h("li", null, link(item))))),
    h("div", { class: "rail-foot" }, h("span", { text: "v" + p.version }),
      h("button", { type: "button", title: "Theme: " + theme, "aria-label": "Change theme (now " + theme + ")", onclick: cycleTheme },
        icon(theme === "dark" ? "moon" : "sun", "sm"), h("span", { text: capital(theme === "auto" ? "Auto" : theme) }))));
  const tabs = h("nav", { class: "tabbar", "aria-label": "Main" }, NAV_MAIN.concat([["more", "More", "more"]]).map(item => link(item, "tab")));
  const stop = p.frozen
    ? h("button", { class: "primary", type: "button", onclick: e => act("admin.unfreeze", {}, { button: e.currentTarget, title: "The AIs can work again" }) }, icon("play", "sm"), h("span", { text: "Let them work" }))
    : !S.seats.length ? null : h("button", { class: "danger stop-btn", type: "button", "data-f": "stop", "aria-label": ui.confirm.stop ? "Click again to stop every AI" : "Stop all AIs", title: "Every AI stops at its next step until you let them work again", onclick: e => confirmStop(e.currentTarget) },
      icon("stop", "sm"), h("span", { class: "long", text: ui.confirm.stop ? "Click again to stop them all" : "Stop all AIs" }),
      h("span", { class: "short", "aria-hidden": "true", text: ui.confirm.stop ? "Sure?" : "Stop" }));
  const top = h("header", { class: "topbar" },
    h("a", { class: "top-brand", href: "#/home", "aria-label": "Roundtable home" }, h("img", { src: "/icon.svg", alt: "" })),
    h("div", { class: "where" }, h("strong", { text: p.name }), h("span", { text: statusLine(S) })),
    stop);
  const frozen = p.frozen ? h("div", { class: "frozen-bar", role: "alert" }, icon("stop"), h("strong", { text: "All AIs are stopped." }),
    h("span", { text: p.frozen_reason ? plainText(p.frozen_reason) : "" })) : null;
  const content = h("main", { class: "content", id: "content" }, (PAGES[page] || PAGES.home)(S));
  return h("div", { class: "shell" }, rail, h("div", { class: "main" }, frozen, top, content), tabs);
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
  if (!ui.confirm.stop) { ui.confirm.stop = true; render(); setTimeout(() => { ui.confirm.stop = false; render(); }, 4000); return; }
  ui.confirm.stop = false;
  act("admin.freeze", { reason: "stopped from the dashboard" }, { button: btn, title: "All AIs stopped" });
}

/* One line for the top bar: what is happening right now. */
function statusLine(st) {
  const p = st.plan;
  const seats = st.seats;
  if (st.project.frozen) return "Paused: every AI is stopped";
  if (!seats.length) return "No AIs yet";
  const notStarted = seats.filter(x => x.status === "active" && !x.joined_ever);
  if (isLivePlan(p) && p.stage === "locked") {
    const { done, total } = progress(st);
    return `Building: ${done} of ${plural(total, "task")} done`;
  }
  if (isLivePlan(p)) return p.stage_label;
  if (notStarted.length === seats.length) return `${plural(seats.length, "AI")} added, not started yet`;
  return p && p.stage === "done" ? "Plan finished. Ready for a new goal" : "Waiting for a goal";
}

function progress(st) {
  const real = st.tasks.filter(t => t.kind !== "epic" && !["cancelled", "backlog"].includes(t.status));
  return { done: real.filter(t => t.status === "done").length, total: real.length, active: real.filter(t => ACTIVE.includes(t.status)).length };
}

/* ---------------------------------------------------------------- page heading with "?" */

const HELP = {
  home: "Home shows what your AIs are doing and the one thing you should do next. The line of steps at the top is the whole journey, from adding AIs to finished work.",
  inbox: "Every decision that waits for you lands here: the plan to approve, changes to check, work the AIs found, problems and votes. When the inbox is empty, there is nothing for you to do.",
  team: "These are the AI models working on your project. Each runs in its own app with your own subscription. Start opens the app for you, already connected to Roundtable.",
  plan: "You write the goal. Each AI drafts a plan without seeing the others, they comment on each other's plans without knowing who wrote which, and one AI combines them. Nothing is built until you approve.",
  work: "Every task in the approved plan. An AI picks it up (In progress), Roundtable runs its tests and another AI checks the changes (Checking), then it is merged into your project (Done).",
  usage: "How much each AI has used of its chat and of its plan's 5-hour and weekly limits, as reported by its app. Roundtable's own messages between AIs are counted too.",
  notes: "Short notes every AI reads when it joins, so a new chat starts with what earlier ones learned. AIs add notes as they work; yours are pinned to the top.",
  history: "Everything that happened in this project, newest first. Search it by word, or by a task number like T3.",
  settings: "How Roundtable behaves for this project. Changes save at once into .roundtable/config.toml; the AIs cannot change them.",
  help: "How Roundtable works, what the words mean, and the terminal command for every button.",
  more: "Pages you will need less often.",
  switch: "Roundtable keeps one table per project folder. Open another folder here, or set Roundtable up in it.",
};

function pageHead(title, lead, ...right) {
  const id = route.page;
  const open = !!ui.help[id];
  const helpBtn = HELP[id] ? h("button", { class: "help-btn", type: "button", "data-f": "help-" + id, "aria-expanded": String(open), "aria-controls": "help-" + id,
    title: "What is this page?", onclick: () => { ui.help[id] = !open; render(); } }, h("span", { "aria-hidden": "true", text: "?" }), h("span", { class: "visually-hidden", text: "What is this page?" })) : null;
  return h("div", { class: "page-head" },
    h("div", { class: "page-title" }, h("div", { class: "title-row" }, h("h1", { text: title }), helpBtn), lead ? h("p", { class: "lead", text: lead }) : null),
    right.length ? h("div", { class: "btn-row" }, right) : null,
    open ? h("p", { class: "help-box", id: "help-" + id, text: HELP[id] }) : null);
}

function panel(title, sub, ...body) {
  return h("section", { class: "panel" },
    title ? h("header", null, h("h2", { text: title }), sub ? h("p", { text: sub }) : null) : null,
    h("div", { class: "panel-body" }, body));
}

function backLink(hash, text) { return h("a", { class: "back", href: hash }, icon("back", "sm"), text); }

/* ---------------------------------------------------------------- set-up screen */

function setupScreen(st) {
  const f = st.setup;
  const notes = [];
  let can = f.exists;
  if (!f.exists) { notes.push(h("p", { class: "note warn", text: "This folder does not exist." })); }
  else if (f.worktree_of) { can = false; notes.push(h("p", { class: "note warn", text: `This is one AI's own copy of a project. Set up Roundtable in the main folder instead: ${f.worktree_of}` })); }
  else if (f.inside) { can = false; notes.push(h("p", { class: "note warn", text: `This folder is inside a git repository. Set up Roundtable at its top folder: ${f.toplevel}` })); }
  else if (!f.git) { notes.push(h("p", { class: "note warn", text: "This folder has no git. Roundtable still works, but every AI shares this one folder. For a separate copy per AI, checked changes and automatic merges, run `git init` here and make a first commit, then reload." })); }
  else if (!f.has_commits) { notes.push(h("p", { class: "note warn", text: "This git repository has no commits yet. Make a first commit before adding AIs that write code: their copies start from it." })); }
  else { notes.push(h("p", { class: "note ok", text: `Git repository on branch ${f.branch || "(detached)"}. Each AI that writes code gets its own copy next to this folder, and finished work is merged into ${f.branch || "your branch"}.` })); }
  const folderIn = h("input", { type: "text", id: "open-folder", "data-k": "open-folder", value: f.folder, spellcheck: "false", autocomplete: "off" });
  const recent = st.recent && st.recent.length ? h("div", { class: "field" }, h("p", { class: "label", text: "Recent projects" }),
    h("ul", { class: "rows" }, st.recent.map(r => h("li", null, h("button", { class: "link-row", type: "button", onclick: e => special("open", { folder: r.root }, { button: e.currentTarget, title: "Opened " + r.name }) },
      icon("folder", "sm"), h("strong", { text: r.name }), h("span", { class: "faint", text: r.root })))))) : null;
  return h("main", { class: "setup", id: "content" }, h("div", { class: "setup-card" },
    h("img", { src: "/icon.svg", alt: "", width: "44", height: "44" }),
    h("h1", { text: "Set up Roundtable here" }),
    h("p", { class: "lead", text: "Several AI models will plan, build and check this project together, each in its own app. Roundtable only adds a hidden .roundtable folder; it never changes your files." }),
    h("dl", { class: "kv" }, h("dt", { text: "Folder" }), h("dd", { class: "mono", text: f.folder })),
    h("div", { class: "stack" }, h("div", null, notes),
      h("div", { class: "btn-row" }, h("button", { class: "primary big", type: "button", disabled: !can, onclick: e => special("init", { folder: f.folder }, { button: e.currentTarget, title: "Roundtable is set up" }) }, "Set up Roundtable in this folder")),
      h("details", { class: "fold", "data-k": "setup-other" }, h("summary", null, icon("chevron", "sm turn"), "Use another folder"),
        h("div", { class: "field" }, h("label", { for: "open-folder", text: "Folder" }),
          h("div", { class: "btn-row" }, folderIn, h("button", { type: "button", onclick: e => special("open", { folder: folderIn.value.trim() }, { button: e.currentTarget, title: "Opened" }) }, "Open")))),
      recent)));
}

PAGES.switch = st => h("div", { class: "stack" },
  pageHead("Open a project", "Switch to another project folder, or set Roundtable up in one."),
  panel(null, null, (() => {
    const input = h("input", { type: "text", id: "switch-folder", "data-k": "switch-folder", placeholder: "/home/you/projects/app", spellcheck: "false" });
    return h("div", { class: "field" }, h("label", { for: "switch-folder", text: "Folder" }),
      h("div", { class: "btn-row" }, input, h("button", { class: "primary", type: "button", onclick: e => special("open", { folder: input.value.trim() }, { button: e.currentTarget, title: "Opened", after: () => go("#/home") }) }, "Open")),
      h("p", { class: "help", text: "If the folder has no Roundtable project yet, you can set one up there next." }));
  })()));

/* ---------------------------------------------------------------- the journey */

const JOURNEY = [
  ["Add AI models", "Start them in their apps."],
  ["Start them", "Give them a goal."],
  ["Give a goal", "They write and agree on a plan."],
  ["They plan", "You read the plan and approve it."],
  ["Approve the plan", "They build, test and check each other's work."],
  ["They build", "Finished work is merged into your project."],
];

function journeyState(st) {
  const p = st.plan;
  const seats = st.seats.filter(x => x.status !== "removed");
  const live = isLivePlan(p);
  const finished = p && p.stage === "done";
  const prog = progress(st);
  const built = finished || (live && p.stage === "locked" && prog.total > 0 && prog.done === prog.total);
  const done = [
    seats.length > 0,
    seats.length > 0 && seats.filter(x => x.status === "active").every(x => x.joined_ever),
    live || finished,
    (live && ["awaiting_human", "locked"].includes(p.stage)) || finished,
    (live && p.stage === "locked") || finished,
    built,
  ];
  // once a plan is under way, starting the AIs counts as done even if one was added later
  if (done[2]) done[1] = true;
  let at = done.findIndex(x => !x);
  return { done, at };
}

function journey(st) {
  const { done, at } = journeyState(st);
  return h("ol", { class: "journey", "aria-label": "Your progress" }, JOURNEY.map(([label], i) => {
    const state = done[i] ? "done" : i === at ? "now" : "later";
    return h("li", { class: state, "aria-current": i === at ? "step" : null },
      h("span", { class: "dot", "aria-hidden": "true" }, done[i] ? icon("check", "xs") : String(i + 1)),
      h("span", { class: "step-label", text: label }),
      h("span", { class: "visually-hidden", text: state === "done" ? " (done)" : state === "now" ? " (current step)" : "" }));
  }));
}

/* ---------------------------------------------------------------- inbox items: every decision in one list */

const GROUPS = [
  ["stop", "Paused"], ["plan", "The plan"], ["review", "Changes to check"], ["found", "Work your AIs found"], ["problem", "Problems"], ["vote", "Votes"],
];
const LEVELS = [[1, "Note", "For the record; nobody has to act."], [2, "Heads-up", "Worth knowing for anyone working nearby."],
  [3, "Problem", "The AIs it affects must acknowledge it before taking new work."], [4, "Blocking", "Holds the affected files until it is fixed."],
  [5, "Critical", "Freezes the files and tells every AI to stop."]];

function inboxItems(st) {
  const items = [];
  const p = st.plan;
  if (st.project.frozen) items.push({ key: "frozen", group: "stop", needs: true, tone: "stop", title: "All AIs are stopped",
    body: plainText(st.project.frozen_reason || "You stopped them."), actions: [{ label: "Let them work again", primary: true, run: b => act("admin.unfreeze", {}, { button: b }) }] });
  if (isLivePlan(p)) {
    if (p.stage === "awaiting_human") items.push({ key: "plan", group: "plan", needs: true, tone: "you", title: "Approve the plan",
      body: `Your AIs agreed on ${plural(p.tasks.length, "task")}. Read it and the test commands it will run, then approve it to start the work.`,
      actions: [{ label: "Read and approve", primary: true, go: "#/plan" }] });
    if (p.overdue) {
      const missing = p.people.filter(x => x.planner && !x.drafted).map(x => x.seat);
      items.push({ key: "overdue", group: "plan", needs: true, tone: "you", title: "Some plans are late",
        body: `Still waiting for ${listWords(missing) || "a draft"}. You can go on with the plans that are in.`,
        actions: [{ label: "Go on without them", primary: true, run: b => act("plan.continue", {}, { button: b }) }] });
    }
    p.amendments.forEach(m => items.push({ key: "amend-" + m.id, group: "plan", needs: m.human, tone: "you",
      title: `${m.by} wants to change the approved plan`,
      body: m.reason, meta: `${m.kind.replace(/_/g, " ")}${m.task ? " on " + m.task : ""}`,
      extra: h("details", { class: "fold small", "data-k": "amend-" + m.id }, h("summary", null, icon("chevron", "sm turn"), "The exact change"), h("div", { class: "output", text: JSON.stringify(m.change, null, 2) })),
      actions: m.human ? [{ label: "Approve the change", primary: true, run: b => act("plan.amend_decide", { id: m.id, decision: "approve" }, { button: b }) },
        { label: "Say no", run: b => act("plan.amend_decide", { id: m.id, decision: "reject" }, { button: b }) }] : [],
      note: m.human ? null : "Waiting for: " + m.needs.join(", ") }));
  }
  st.reviews.forEach(r => items.push({ key: "review-" + r.task, group: "review", needs: true, tone: "you", title: `Check the changes in ${r.task}: ${r.title}`,
    body: "No AI from another company could check this one, so it comes to you. Read the changes, then approve them or say what must change.",
    actions: [{ label: "Review changes", primary: true, go: "#/inbox/review/" + r.task }] }));
  st.level_requests.forEach(q => items.push({ key: "level-" + q.id, group: "review", needs: true, tone: "you",
    title: `${q.seat} wants ${(CHECKING[q.level] || q.level).toLowerCase()} checking for ${q.task}`, body: q.reason,
    actions: [{ label: "Allow", primary: true, run: b => act("review.level_decide", { id: q.id, decision: "approve" }, { button: b }) },
      { label: "Keep it as it is", run: b => act("review.level_decide", { id: q.id, decision: "deny" }, { button: b }) }] }));
  st.tasks.filter(t => t.status === "backlog").forEach(t => items.push(foundItem(st, t)));
  st.tasks.filter(t => t.status === "merge_blocked").forEach(t => items.push({ key: "merge-" + t.id, group: "problem", needs: true, tone: "warn",
    title: `${t.id} is approved but can't be merged yet`, body: plainText(t.merge_note) || "Your project folder has unsaved changes, or is on another branch. Fix that, then try again.",
    actions: [{ label: "Try again", primary: true, run: b => act("task.merge", { task: t.id }, { button: b }) }, { label: "Details", go: "#/work/" + t.id }] }));
  st.alerts.forEach(a => items.push(alertItem(a)));
  st.votes.forEach(v => items.push(voteItem(v)));
  return items;
}

function foundItem(st, t) {
  const ready = t.kind === "epic" || (t.files.length && t.proof.length);
  const open = ui.accepting[t.id];
  const builders = st.seats.filter(x => x.roles.includes("build") && x.status === "active");
  return { key: "found-" + t.id, group: "found", needs: true, tone: "you", title: t.title,
    meta: `${t.id}, ${t.filed_by && t.filed_by !== "human" ? "found by " + t.filed_by : "added by you"}${t.kind !== "task" ? ", " + t.kind : ""}${t.priority < 2 ? ", " + PRIORITY[t.priority].toLowerCase() + " priority" : ""}`,
    body: plainText(t.summary),
    extra: open || !ready ? (open ? acceptForm(t, builders) : h("p", { class: "faint", text: "Before it can start, say which files it may change and how to test it." })) : null,
    actions: [
      open ? null : ready
        ? { label: "Accept", primary: true, run: b => act("task.accept", { task: t.id }, { button: b, title: "Accepted " + t.id }) }
        : { label: "Accept…", primary: true, run: () => { ui.accepting[t.id] = true; render(); } },
      { label: "Not needed", run: b => act("task.cancel", { task: t.id, reason: "not needed (decided in the inbox)" }, { button: b, title: "Removed " + t.id }) },
      { label: "Details", go: "#/work/" + t.id, quiet: true },
    ].filter(Boolean) };
}

function acceptForm(d, builders) {
  const files = h("input", { type: "text", id: "acc-files-" + d.id, "data-k": "acc-files-" + d.id, value: d.files.join(", "), spellcheck: "false", placeholder: "src/search.py, tests/test_search.py" });
  const proof = h("input", { type: "text", id: "acc-proof-" + d.id, "data-k": "acc-proof-" + d.id, value: d.proof.join(" && "), spellcheck: "false", placeholder: "python -m pytest -q tests/test_search.py" });
  const owner = h("select", { id: "acc-owner-" + d.id, "data-k": "acc-owner-" + d.id }, h("option", { value: "" }, "Whichever AI is free"), builders.map(x => h("option", { value: x.handle }, x.handle)));
  return h("div", { class: "inline-form" },
    h("div", { class: "field" }, h("label", { for: "acc-files-" + d.id, text: "Files it may change" }), h("span", { class: "help", text: "Separate with commas. Patterns like src/** work." }), files),
    h("div", { class: "field" }, h("label", { for: "acc-proof-" + d.id, text: "Test command" }), h("span", { class: "help", text: "Runs on your computer when the work is done, to prove it works." }), proof),
    h("div", { class: "field" }, h("label", { for: "acc-owner-" + d.id, text: "Who does it" }), owner),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => act("task.accept",
      { task: d.id, files: csv(files.value), proof: cmds(proof.value).length ? cmds(proof.value) : null, owner: owner.value || null },
      { button: e.currentTarget, title: "Accepted " + d.id, after: () => { delete ui.accepting[d.id]; } }) }, "Accept as work"),
      ui.accepting[d.id] ? h("button", { class: "quiet", type: "button", onclick: () => { delete ui.accepting[d.id]; render(); } }, "Cancel") : null));
}

function alertItem(a) {
  const lvl = LEVELS[a.level - 1] || LEVELS[2];
  const note = h("input", { type: "text", "data-k": "res-" + a.id, placeholder: "What fixed it (optional)", "aria-label": "What fixed it" });
  const lvlSel = h("select", { "aria-label": "How serious", onchange: e => act("alert.set_level", { id: a.id, level: Number(e.target.value) }) },
    LEVELS.map(([n, name]) => h("option", { value: String(n), selected: n === a.level ? true : null }, `${n}. ${name}`)));
  return { key: "alert-" + a.id, group: "problem", needs: a.level >= 3 || !!a.proposed, tone: a.level >= 4 ? "stop" : a.level === 3 ? "warn" : "idle",
    badge: `${lvl[1]}`, title: a.title, meta: `${a.id}, reported by ${who(a.by)} ${a.at}`,
    body: a.description,
    extra: h("div", { class: "stack-sm" },
      h("p", { class: "faint", text: lvl[2] + (a.must_ack.length ? ` Acknowledged by ${listWords(a.acked) || "nobody yet"} of ${listWords(a.must_ack)}.` : "") }),
      a.proposed ? h("p", { class: "note warn" }, `${a.proposed_by} thinks this is level ${a.proposed} (${LEVELS[a.proposed - 1][1]}). `,
        h("button", { class: "link", type: "button", onclick: e => act("alert.set_level", { id: a.id, level: a.proposed }, { button: e.currentTarget }) }, `Change it to ${a.proposed}`)) : null,
      a.files.length ? h("p", { class: "small" }, "Files: ", h("span", { class: "mono", text: a.files.join(", ") })) : null,
      a.evidence ? h("details", { class: "fold small", "data-k": "ev-" + a.id }, h("summary", null, icon("chevron", "sm turn"), "Evidence"), h("div", { class: "output", text: a.evidence })) : null,
      h("div", { class: "btn-row" }, note, h("button", { class: "primary", type: "button", onclick: e => act("alert.resolve", { id: a.id, resolution: note.value.trim() || "resolved by the human" }, { button: e.currentTarget, title: "Marked as fixed" }) }, "Mark as fixed"), lvlSel)),
    actions: [] };
}

function voteItem(v) {
  const tied = v.status === "tied";
  return { key: "vote-" + v.id, group: "vote", needs: tied, tone: tied ? "you" : "idle", title: v.topic,
    meta: tied ? "The AIs are split evenly. You decide." : `The AIs are voting (${v.ballots.length} of ${v.voters.length} in). You can decide now if you want.`,
    extra: h("ul", { class: "tally" }, v.options.map(o => {
      const bs = v.ballots.filter(b => b.choice === o);
      return h("li", null, h("p", null, h("strong", { text: o }), h("span", { class: "faint", text: `  ${plural(bs.length, "vote")}` })),
        bs.map(b => h("p", { class: "muted small", text: `${b.seat}: ${b.reason}` })));
    })),
    actions: v.options.map(o => ({ label: "Choose " + fit(o, 32), run: b => act("vote.decide", { id: v.id, choice: o }, { button: b }) })) };
}

function itemActions(it) {
  return (it.actions || []).map(a => a.go
    ? h("a", { class: "btn" + (a.primary ? " primary" : a.quiet ? " quiet" : ""), href: a.go }, a.label, a.primary ? icon("arrow", "sm") : null)
    : h("button", { type: "button", class: a.primary ? "primary" : a.quiet ? "quiet" : "", onclick: e => a.run(e.currentTarget) }, a.label));
}

function inboxCard(it) {
  const acts = itemActions(it);
  return h("article", { class: "item tone-" + it.tone, id: it.key },
    h("div", { class: "item-head" }, it.badge ? h("span", { class: "badge tone-" + it.tone, text: it.badge }) : null, h("h3", { text: it.title })),
    it.meta ? h("p", { class: "faint", text: it.meta }) : null,
    it.body ? h("p", { class: "item-body pre", text: it.body }) : null,
    it.extra || null,
    it.note ? h("p", { class: "faint", text: it.note }) : null,
    acts.length ? h("div", { class: "btn-row" }, acts) : null);
}

/* ---------------------------------------------------------------- home */

function nextStep(st, items) {
  const p = st.plan;
  const seats = st.seats;
  const urgent = items.filter(i => i.needs);
  const { at } = journeyState(st);
  const then = at >= 0 ? JOURNEY[at][1] : null;
  if (st.project.frozen) return { eyebrow: "Paused", title: "All AIs are stopped", body: "None of them will take another step until you let them work again.",
    primary: { label: "Let them work again", run: b => act("admin.unfreeze", {}, { button: b, title: "The AIs can work again" }) } };
  if (!seats.length) return { eyebrow: "Your next step", title: "Add your first AI model",
    body: "Pick the app it runs in: Claude Code, Codex, Gemini, a code editor or a desktop app. It uses your own subscription; no API keys.",
    primary: { label: "Add an AI model", go: "#/team/add" }, then };
  if (p && p.stage === "awaiting_human" && isLivePlan(p)) return { eyebrow: "Your next step", title: "Approve the plan",
    body: `Your AIs agreed on a plan with ${plural(p.tasks.length, "task")}. Read it and the test commands it will run on your computer, then approve it.`,
    primary: { label: "Read and approve", go: "#/plan" }, then: JOURNEY[4][1] };
  if (urgent.length) {
    const first = urgent[0];
    const action = (first.actions || []).find(a => a.primary);
    const said = { stop: "the AIs are stopped", plan: "the plan needs you", review: "there are changes to check", found: "your AIs found more work",
      problem: "a problem was reported", vote: "a vote is tied" };
    const groups = GROUPS.map(g => g[0]).filter(g => urgent.some(i => i.group === g));
    return { eyebrow: "Your next step", title: urgent.length === 1 ? first.title : `${urgent.length} things need your decision`,
      body: urgent.length === 1 ? (first.body || first.meta || "") : capital(listWords(groups.map(g => said[g]))) + ". Each one is in your inbox with the buttons that settle it.",
      primary: urgent.length === 1 && action && action.go ? action : { label: "Open your inbox", go: "#/inbox" }, then };
  }
  const notStarted = seats.filter(x => x.status === "active" && !x.joined_ever);
  if (seats.length === 1 && !isLivePlan(p)) return { eyebrow: "Your next step", title: "Add a second AI model",
    body: "One AI can work alone, but two from different companies catch each other's mistakes.",
    primary: { label: "Add an AI model", go: "#/team/add" }, secondary: { label: notStarted.length ? "Start " + seats[0].handle : "Give a goal instead", go: notStarted.length ? "#/team" : "#/plan" }, then };
  if (notStarted.length && !isLivePlan(p)) return { eyebrow: "Your next step", title: `Start ${listWords(notStarted.map(x => x.handle))}`,
    body: "Each AI works in its own app. Start it once and it joins the table; terminal apps open by themselves.",
    primary: { label: notStarted.length === 1 ? "Start " + notStarted[0].handle : "Start them", go: "#/team" }, then };
  if (!isLivePlan(p)) return { eyebrow: "Your next step", title: p && p.stage === "done" ? "Give your AIs the next goal" : "Give your AIs a goal",
    body: "Say what to build and how you will know it works. They each plan it, compare notes and agree on one plan for you to approve.",
    primary: { label: "Write the goal", go: "#/plan" }, then };
  if (p.stage !== "locked") return { eyebrow: "Nothing to do right now", calm: true, title: "Your AIs are planning",
    body: `${p.stage_label}. The plan comes to your inbox when they agree.`,
    primary: { label: "Watch the plan", go: "#/plan" }, then: JOURNEY[3][1] };
  const pr = progress(st);
  if (pr.total && pr.done === pr.total) return { eyebrow: "Finished", calm: true, title: "Every task is done",
    body: "All the work in this plan has been tested, checked and merged into your project.",
    primary: { label: "Give the next goal", go: "#/plan" } };
  return { eyebrow: "Nothing to do right now", calm: true, title: "Your AIs are building",
    body: `${pr.done} of ${plural(pr.total, "task")} done, ${pr.active} in progress or being checked. New decisions show up in your inbox.`,
    primary: { label: "See the work", go: "#/work" }, then: JOURNEY[5][1] };
}

function nextCard(n) {
  const btn = a => a.go ? h("a", { class: "btn " + (a === n.primary ? "primary big" : "ghost"), href: a.go }, a.label, a === n.primary ? icon("arrow", "sm") : null)
    : h("button", { class: a === n.primary ? "primary big" : "ghost", type: "button", onclick: e => a.run(e.currentTarget) }, a.label);
  return h("section", { class: "next" + (n.calm ? " calm" : ""), "aria-labelledby": "next-title" },
    h("p", { class: "eyebrow", text: n.eyebrow }),
    h("h2", { id: "next-title", text: n.title }),
    n.body ? h("p", { class: "next-body", text: n.body }) : null,
    h("div", { class: "btn-row" }, btn(n.primary), n.secondary ? btn(n.secondary) : null),
    n.then ? h("p", { class: "then" }, h("span", { text: "After that: " }), n.then) : null);
}

PAGES.home = st => {
  const items = inboxItems(st);
  const n = nextStep(st, items);
  const urgent = items.filter(i => i.needs);
  const summarised = urgent.length > 1 && n.title.endsWith("need your decision");
  const others = summarised ? [] : urgent.filter(i => n.title !== i.title).slice(0, 4);
  const p = st.plan;
  const pr = progress(st);
  const working = st.tasks.filter(t => ACTIVE.includes(t.status));
  return h("div", { class: "stack-lg" },
    pageHead("Home", isLivePlan(p) ? "Goal: " + p.goal : null),
    journey(st),
    h("div", { class: "home-grid" },
      h("div", { class: "stack" }, nextCard(n),
        others.length ? h("section", { class: "plain-section" }, h("div", { class: "section-head" }, h("h2", { text: "Also waiting for you" }), h("a", { href: "#/inbox", text: "Open your inbox" })),
          h("ul", { class: "rows compact" }, others.map(i => h("li", null, h("a", { class: "row-link", href: "#/inbox" }, h("span", { class: "dot-mark tone-" + i.tone }), h("span", { text: i.title }), icon("chevron", "sm")))))) : null,
        isLivePlan(p) && p.stage === "locked" && pr.total ? h("section", { class: "plain-section" },
          h("div", { class: "section-head" }, h("h2", { text: "The work" }), h("a", { href: "#/work", text: "Open the board" })),
          progressBar(st),
          working.length ? h("ul", { class: "rows compact" }, working.slice(0, 5).map(t => h("li", null, h("a", { class: "row-link", href: "#/work/" + t.id },
            h("span", { class: "id", text: t.id }), h("span", { class: "grow", text: t.title }), h("span", { class: "faint", text: cardStatus(t) }))))) : null) : null),
      h("section", { class: "panel table-panel", "aria-labelledby": "table-title" },
        h("div", { class: "section-head" }, h("h2", { id: "table-title", text: "At the table" }), h("a", { href: "#/team", text: st.seats.length ? "Your team" : "Add AIs" })),
        theTable(st), seatLines(st))),
    h("section", { class: "plain-section" }, h("div", { class: "section-head" }, h("h2", { text: "Latest" }), h("a", { href: "#/history", text: "All history" })),
      feed(st.events.slice(0, 8))));
};

function progressBar(st) {
  const cols = boardColumns(st);
  return h("div", { class: "progress", role: "img", "aria-label": cols.map(c => `${c.label}: ${c.items.length}`).join(", ") },
    h("div", { class: "progress-bar" }, cols.map(c => { const seg = h("span", { class: "seg-" + c.id }); seg.style.flexGrow = String(c.items.length); return c.items.length ? seg : null; })),
    h("ul", { class: "progress-key" }, cols.map(c => h("li", null, h("i", { class: "seg-" + c.id }), `${c.label} `, h("strong", { text: String(c.items.length) })))));
}

function seatState(seat) {
  if (seat.status === "paused") return ["paused", "Paused"];
  if (!seat.joined_ever) return ["idle", "Not started yet"];
  if (seat.tasks.length) return ["working", "Working on " + seat.tasks.join(", ")];
  if (seat.live) return ["live", seat.doing ? capital(plainText(seat.doing)) : "Online, waiting for work"];
  return ["idle", /^\d+s\b/.test(seat.seen) ? "Away, seen just now" : "Away, last seen " + seat.seen];
}

function seatLines(st) {
  if (!st.seats.length) return h("p", { class: "empty", text: "Nobody yet. Add two or more AI models, ideally from different companies." });
  return h("ul", { class: "seat-lines" }, st.seats.map(x => {
    const [cls, note] = seatState(x);
    return h("li", null, h("a", { href: "#/team/" + x.handle }, h("span", { class: "state-dot " + cls, "aria-hidden": "true" }), h("strong", { text: x.handle }), h("span", { class: "faint", text: note })));
  }));
}

function theTable(st) {
  const W = 420, H = 300, cx = W / 2, cy = 150, rx = 112, ry = 62;
  const seats = st.seats.filter(x => x.status !== "removed");
  const svg = s("svg", { class: "table-svg", viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": seats.length ? "The table: " + seats.map(x => `${x.handle} ${seatState(x)[1]}`).join("; ") : "The table is empty" });
  svg.append(s("defs", null, s("marker", { id: "arrow", viewBox: "0 0 8 8", refX: "6", refY: "4", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" },
    s("path", { d: "M0 0L8 4L0 8z", class: "chord-head" }))));
  svg.append(s("ellipse", { class: "cloth", cx, cy, rx, ry }), s("ellipse", { class: "cloth-inner", cx, cy, rx: rx - 11, ry: ry - 9 }));
  const pos = {};
  const n = seats.length;
  seats.forEach((seat, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(n, 1);
    pos[seat.handle] = { x: cx + (rx + 46) * Math.cos(a), y: cy + (ry + 38) * Math.sin(a), a };
  });
  const chords = [];
  if (st.plan && st.plan.stage === "critique") (st.plan.critique_pairs || []).forEach(pair => chords.push(pair));
  st.tasks.filter(t => t.status === "in_review").forEach(t => (t.reviewers || []).forEach(r => chords.push([r, t.owner])));
  chords.forEach(([from, to]) => {
    if (!pos[from] || !pos[to] || from === to) return;
    const A = pos[from], B = pos[to];
    svg.append(s("path", { class: "chord", d: `M${A.x} ${A.y} Q${cx} ${cy} ${B.x} ${B.y}`, "marker-end": "url(#arrow)" }));
  });
  const plan = st.plan;
  const pr = progress(st);
  const line1 = !seats.length ? "An empty table" : !isLivePlan(plan) ? (plan && plan.stage === "done" ? "Plan finished" : "Waiting for a goal")
    : plan.stage === "locked" ? `${pr.done} of ${pr.total} done` : plan.stage === "awaiting_human" ? "Waiting for you" : "Planning";
  const line2 = isLivePlan(plan) && plan.stage === "locked" ? "building" : seats.length ? plural(seats.length, "AI") : "add AIs to begin";
  svg.append(s("text", { class: "phase", x: cx, y: cy - 1, "text-anchor": "middle" }, fit(line1, 26)),
    s("text", { class: "phase-sub", x: cx, y: cy + 18, "text-anchor": "middle" }, line2));
  seats.forEach(seat => {
    const p = pos[seat.handle];
    const [cls] = seatState(seat);
    const g = s("a", { href: "#/team/" + seat.handle, "aria-label": `${seat.handle}: ${seatState(seat)[1]}` });
    g.append(s("circle", { class: "seat-disc " + cls, cx: p.x, cy: p.y, r: 19 }),
      s("text", { class: "seat-mono", x: p.x, y: p.y + 4.5, "text-anchor": "middle" }, monogram(seat.handle)));
    const below = Math.sin(p.a) > -0.3;
    g.append(s("text", { class: "seat-name", x: p.x, y: below ? p.y + 35 : p.y - 27, "text-anchor": "middle" }, seat.handle));
    svg.append(g);
  });
  return svg;
}

function feed(events, opts) {
  if (!events.length) return h("p", { class: "empty", text: "Nothing has happened yet." });
  const items = [];
  let day = "";
  events.forEach(e => {
    if (e.day !== day) { day = e.day; items.push(h("li", { class: "day", text: day })); }
    let text = e.text;
    if (text.startsWith(e.actor + " ")) text = text.slice(e.actor.length + 1);
    if (e.actor === "human" && text.startsWith("the human ")) text = text.slice(10);
    if (e.task && text.startsWith(e.task)) text = text.slice(e.task.length).replace(/^:? ?/, "");
    items.push(h("li", { class: e.level >= 4 ? "hi" : "" }, h("span", { class: "t", text: e.at }), h("span", { class: "who", text: who(e.actor) }),
      h("span", { class: "what" }, e.task ? [h("a", { class: "id", href: "#/work/" + e.task, text: e.task }), " "] : null, plainText(text))));
  });
  return h("ul", { class: "feed" + (opts && opts.full ? " full" : "") }, items);
}

/* ---------------------------------------------------------------- inbox */

PAGES.inbox = st => {
  if (route.sub === "review" && route.parts[1]) {
    const id = route.parts[1].toUpperCase();
    return h("div", { class: "stack" }, backLink("#/inbox", "Inbox"), pageHead("Check " + id, (st.tasks.find(t => t.id === id) || {}).title || ""), reviewBlock(st, id));
  }
  const items = inboxItems(st);
  const waiting = items.filter(i => i.needs).length;
  const present = GROUPS.filter(([g]) => items.some(i => i.group === g));
  if (!present.some(([g]) => g === ui.inboxFilter)) ui.inboxFilter = "all";
  const shown = ui.inboxFilter === "all" ? items : items.filter(i => i.group === ui.inboxFilter);
  const filters = present.length > 1 ? h("div", { class: "filters", role: "group", "aria-label": "Show" },
    [["all", "Everything"]].concat(present).map(([g, label]) => h("button", { type: "button", "aria-pressed": String(ui.inboxFilter === g),
      onclick: () => { ui.inboxFilter = g; render(); } }, label, h("span", { class: "n", text: String(g === "all" ? items.length : items.filter(i => i.group === g).length) })))) : null;
  return h("div", { class: "stack" },
    pageHead("Inbox", items.length ? (waiting ? `${plural(waiting, "thing")} waiting for your decision.` : "Nothing needs you; these are for your information.") : null),
    items.length ? filters : null,
    items.length ? GROUPS.filter(([g]) => shown.some(i => i.group === g)).map(([g, label]) => h("section", { class: "group", "aria-labelledby": "g-" + g },
      h("h2", { class: "group-head", id: "g-" + g, text: label }), shown.filter(i => i.group === g).map(inboxCard)))
      : h("div", { class: "all-clear" }, h("span", { class: "big-check", "aria-hidden": "true" }, icon("check")), h("div", null, h("h2", { text: "You're all caught up" }),
        h("p", { text: "When your AIs need a decision, it shows up here. Leave this page open, or run rt watch for desktop notifications." }))),
    h("details", { class: "fold", "data-k": "raise" }, h("summary", null, icon("chevron", "sm turn"), "Tell your AIs about a problem yourself"), raiseForm()));
};

function reviewBlock(st, id) {
  const d = cache.diff[id];
  if (!d) { getJSON("/api/diff?task=" + encodeURIComponent(id)).then(x => { cache.diff[id] = x; render(); }); return panel(null, null, h("p", { class: "empty", text: "Loading the changes…" })); }
  const pts = h("textarea", { id: "rv-points", "data-k": "rv-" + id, rows: "4", placeholder: "One point per line: what is good, what must change" });
  const lines = (d.diff || "").split("\n");
  const diff = d.diff ? h("div", { class: "diff", role: "region", "aria-label": "Changes", tabindex: "0" }, lines.map(l => h("div", {
    class: l.startsWith("diff --git") || l.startsWith("+++") || l.startsWith("---") ? "file" : l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "",
    text: l || " " }))) : h("p", { class: "note", text: d.note || "No changes." });
  const send = verdict => e => {
    const points = pts.value.split("\n").map(x => x.trim()).filter(Boolean);
    if (verdict === "changes" && !points.length) { toast("Say what must change", "Write at least one point; the AI works from it."); pts.focus(); return; }
    act("review.submit", { task: id, verdict, points: points.length ? points : null }, { button: e.currentTarget, after: () => { delete cache.diff[id]; go("#/inbox"); } });
  };
  return h("div", { class: "stack" },
    h("p", { class: "muted", text: "Green lines were added, red lines removed. Approve if it does what the task says; otherwise write what must change." }),
    diff,
    panel(null, null,
      h("div", { class: "field" }, h("label", { for: "rv-points", text: "Your notes" }), h("span", { class: "help", text: "Optional when you approve." }), pts),
      h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: send("approve") }, icon("check", "sm"), "Approve the changes"),
        h("button", { type: "button", onclick: send("changes") }, "Ask for changes"))));
}

function raiseForm() {
  const lvl = h("select", { id: "al-level", "data-k": "al-level" }, LEVELS.map(([n, name]) => h("option", { value: String(n), selected: n === 3 ? true : null }, `${n}. ${name}`)));
  const lvlHelp = h("span", { class: "help", text: LEVELS[2][2] });
  lvl.addEventListener("change", () => { lvlHelp.textContent = LEVELS[Number(lvl.value) - 1][2]; });
  const title = h("input", { type: "text", id: "al-title", "data-k": "al-title" });
  const desc = h("textarea", { id: "al-desc", "data-k": "al-desc", rows: "3" });
  const files = h("input", { type: "text", id: "al-files", "data-k": "al-files", placeholder: "src/auth/**", spellcheck: "false" });
  return h("div", { class: "fold-body form-grid" },
    h("div", { class: "field wide" }, h("label", { for: "al-title", text: "What is wrong" }), title),
    h("div", { class: "field wide" }, h("label", { for: "al-desc", text: "Details" }), desc),
    h("div", { class: "field" }, h("label", { for: "al-level", text: "How serious" }), lvl, lvlHelp),
    h("div", { class: "field" }, h("label", { for: "al-files", text: "Files it affects (optional)" }), files),
    h("div", { class: "btn-row wide" }, h("button", { class: "primary", type: "button", onclick: e => {
      if (!title.value.trim()) { toast("Say what is wrong", ""); title.focus(); return; }
      act("alert.raise", { level: Number(lvl.value), title: title.value.trim(), description: desc.value.trim() || null, files: files.value.trim() || null },
        { button: e.currentTarget, title: "Your AIs have been told", after: () => { title.value = ""; desc.value = ""; files.value = ""; } });
    } }, "Tell the AIs")));
}

/* ---------------------------------------------------------------- plan */

const STAGE_STEPS = [["drafting", "Each writes a plan"], ["critique", "They comment"], ["merging", "Plans combined"], ["proposed", "They agree"], ["awaiting_human", "You approve"], ["locked", "Building"]];

PAGES.plan = st => {
  const p = st.plan;
  if (!isLivePlan(p)) return h("div", { class: "stack" },
    pageHead("Plan", "Tell your AIs what to build. They plan it together and bring you one plan to approve."),
    goalForm(st), p ? h("p", { class: "faint", text: `Last plan (${p.id}) ${p.stage === "done" ? "was finished" : "was cancelled"}: ${p.goal}` }) : null);
  const at = STAGE_STEPS.findIndex(x => x[0] === (p.stage === "voting" ? "proposed" : p.stage));
  const line = h("ol", { class: "stage-line", "aria-label": "Planning steps" }, STAGE_STEPS.map(([id, label], i) =>
    h("li", { class: i < at ? "past" : i === at ? "now" : "", "aria-current": i === at ? "step" : null }, h("span", { text: label }))));
  const people = p.people.length ? h("ul", { class: "people" }, p.people.map(x => h("li", null,
    h("strong", { text: x.seat }), x.chair ? h("span", { class: "tag", text: "combines the plans" }) : null,
    h("span", { class: "faint", text: [
      x.planner ? (x.drafted ? "wrote a plan" : "writing a plan…") : null,
      x.critiques ? `commented on ${x.critiques_done} of ${x.critiques}` : null,
      x.approval ? (x.approval.decision === "approve" ? "agreed" : "objected" + (x.approval.reason ? `: ${x.approval.reason}` : "")) : null,
    ].filter(Boolean).join(", ") || "waiting" })))) : null;
  const approving = p.stage === "awaiting_human" || (["proposed", "voting"].includes(p.stage) && p.tasks.length);
  return h("div", { class: "stack" },
    pageHead("Plan " + p.id, null),
    h("section", { class: "goal-quote" }, h("p", { class: "eyebrow", text: "The goal" }), h("blockquote", { text: p.goal })),
    approving && p.stage === "awaiting_human" ? approveBlock(p, false) : null,
    panel(p.stage_label, `Since ${p.since}.` + (p.revisions ? ` Revised ${plural(p.revisions, "time")}.` : ""), h("div", { class: "stack" }, line, people,
      p.overdue ? h("div", { class: "note warn" }, h("p", { text: "Some plans are late. You can go on with the ones that are in." }),
        h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => act("plan.continue", {}, { button: e.currentTarget }) }, "Go on without them"))) : null)),
    approving && p.stage !== "awaiting_human" ? approveBlock(p, true) : null,
    p.proposal || p.tasks.length ? panel(p.proposal ? "The combined plan" : "The plan", p.chair ? `Combined by ${p.chair}.` : null,
      p.proposal ? h("p", { class: "pre prose", text: p.proposal }) : null, specList(p.tasks)) : null,
    p.drafts.length ? panel("Each AI's own plan", p.stage === "drafting" ? "The AIs cannot see each other's plans until every plan is in. You can." : "The AIs saw these as Plan A, B, C, without names.",
      p.drafts.map(d => draftBlock(d, p))) : null,
    p.amendments.length ? h("p", { class: "note" }, `${plural(p.amendments.length, "change")} to the approved plan ${p.amendments.length === 1 ? "is" : "are"} waiting. `, h("a", { href: "#/inbox", text: "Decide in your inbox" })) : null,
    cancelPlanBlock(p));
};

function approveBlock(p, early) {
  const ack = h("input", { type: "checkbox", id: "lock-ack", "data-k": "lock-ack" });
  const btn = h("button", { class: "primary big", type: "button", onclick: e => {
    if (!ack.checked) { toast("Tick the box first", "These commands will run on your computer. Read them, then tick the box."); return; }
    act("plan.lock", early ? { force: true } : {}, { button: e.currentTarget, title: "Plan approved. The AIs can start." });
  } }, early ? "Approve without waiting" : "Approve the plan");
  const body = h("div", { class: "stack" },
    early ? h("p", { class: "muted", text: "Not every AI has agreed yet. You can approve anyway; their objections are listed above." }) : h("p", { text: "When you approve, the AIs start building. After each task, Roundtable runs its test command on your computer to prove the work is right." }),
    h("div", null, h("h3", { class: "small-head", text: "These commands will run on your computer" }),
      h("div", { class: "output", text: p.commands.length ? p.commands.join("\n") : "(no commands)" })),
    h("label", { class: "check", for: "lock-ack" }, ack, h("span", null, "I have read these commands and they are safe to run here")),
    h("div", { class: "btn-row" }, btn));
  if (early) return h("details", { class: "fold panel-fold", "data-k": "approve-early" }, h("summary", null, icon("chevron", "sm turn"), "Approve now, without waiting for every AI"), body);
  return h("section", { class: "approve", "aria-labelledby": "approve-title" }, h("p", { class: "eyebrow", text: "Your decision" }), h("h2", { id: "approve-title", text: "Approve the plan" }), body);
}

function specList(specs) {
  if (!specs || !specs.length) return null;
  return h("ol", { class: "spec-list" }, specs.map(t => h("li", null,
    h("div", { class: "spec-title" }, h("strong", { text: t.title }), t.kind && t.kind !== "task" ? h("span", { class: "tag", text: t.kind }) : null,
      t.priority !== undefined && t.priority < 2 ? h("span", { class: "tag warn", text: PRIORITY[t.priority] }) : null),
    t.summary ? h("p", { class: "muted small", text: t.summary }) : null,
    h("dl", { class: "spec-meta" },
      h("dt", { text: "Who" }), h("dd", { text: t.owner || "whichever AI is free" }),
      t.depends_on && t.depends_on.length ? [h("dt", { text: "After" }), h("dd", { text: "task " + t.depends_on.join(", ") })] : null,
      (t.files || []).length ? [h("dt", { text: "Files" }), h("dd", { class: "mono", text: t.files.join(", ") })] : null,
      (t.proof || []).length ? [h("dt", { text: "Tested by" }), h("dd", { class: "mono", text: t.proof.join(" && ") })] : null))));
}

function draftBlock(d, p) {
  const crits = p.critiques.filter(c => c.draft === d.label);
  return h("details", { class: "draft", "data-k": "draft-" + (d.label || d.author) },
    h("summary", null, icon("chevron", "sm turn"), h("strong", { text: d.label ? `Plan ${d.label}` : "Plan" }), h("span", { class: "muted", text: `by ${d.author}` }),
      h("span", { class: "faint", text: `${plural(d.tasks.length, "task")}, ${plural(crits.length, "comment")}` })),
    h("p", { class: "pre prose", text: d.text }), specList(d.tasks),
    crits.map(c => h("div", { class: "note" }, h("strong", { text: `Comments from ${c.critic}` }),
      h("ul", { class: "points" }, c.points.map(pt => h("li", null, h("span", { class: "verdict-" + (pt.verdict || "change"), text: ({ keep: "Keep", change: "Change", drop: "Drop" }[pt.verdict] || capital(pt.verdict || "")) + ": " }), pt.text))))));
}

function cancelPlanBlock(p) {
  if (!ui.cancelPlan) return h("div", { class: "btn-row" }, h("button", { class: "quiet", type: "button", onclick: () => { ui.cancelPlan = true; render(); } }, "Cancel this plan…"));
  const reason = h("input", { type: "text", id: "cancel-reason", "data-k": "cancel-reason", placeholder: "Why (the AIs will read this)" });
  return panel("Cancel the plan", "Unfinished tasks are cancelled too. Work already merged stays.",
    h("div", { class: "field" }, h("label", { for: "cancel-reason", text: "Reason" }), reason),
    h("div", { class: "btn-row" }, h("button", { class: "danger solid", type: "button", onclick: e => {
      if (!reason.value.trim()) { toast("Add a reason", "The AIs read it, so they know what changed."); return; }
      act("plan.cancel", { reason: reason.value.trim() }, { button: e.currentTarget, after: () => { ui.cancelPlan = false; } });
    } }, "Cancel the plan"), h("button", { type: "button", onclick: () => { ui.cancelPlan = false; render(); } }, "Keep it")));
}

function goalForm(st) {
  if (!st.seats.length) return h("section", { class: "next calm" }, h("p", { class: "eyebrow", text: "First" }), h("h2", { text: "Add your AI models" }),
    h("p", { class: "next-body", text: "A plan needs AIs to write it. Add two or more, ideally from different companies." }),
    h("div", { class: "btn-row" }, h("a", { class: "btn primary big", href: "#/team/add" }, "Add an AI model", icon("arrow", "sm"))));
  const planners = st.seats.filter(x => x.status === "active" && x.roles.includes("plan"));
  const goal = h("textarea", { id: "goal", "data-k": "goal", rows: "5", placeholder: "Add a search box to the log page. It should ignore upper and lower case, and come with tests." });
  const level = st.project.review;
  return panel(null, null,
    h("div", { class: "field" }, h("label", { class: "big-label", for: "goal", text: "What should your AIs build?" }),
      h("span", { class: "help", text: "Be specific: what, where, and how you will know it works." }), goal),
    h("fieldset", { class: "field" }, h("legend", { text: "How carefully should they check each other's work?" }),
      h("div", { class: "choices three" }, ["low", "mid", "high"].map(v => h("label", { class: "choice" },
        h("input", { type: "radio", name: "level", value: v, "data-k": "level-" + v, checked: v === level }),
        h("div", null, h("strong", { text: CHECKING[v] }), h("span", { text: CHECKING_TEXT[v] })))))),
    planners.length > 1 ? h("details", { class: "fold", "data-k": "planners" }, h("summary", null, icon("chevron", "sm turn"), `Who writes a plan (${planners.length > 3 ? "up to three" : "all of them"})`),
      h("div", { class: "choices row" }, planners.map((x, i) => h("label", { class: "check" },
        h("input", { type: "checkbox", "data-k": "planner-" + x.handle, value: x.handle, checked: i < 3, class: "planner" }),
        h("span", null, h("strong", { text: x.handle }), h("small", { text: x.model })))))) : null,
    !planners.length ? h("p", { class: "note warn", text: "None of your AIs is set to write plans. Change that on the Team page." }) : null,
    h("div", { class: "btn-row" }, h("button", { class: "primary big", type: "button", onclick: e => {
      const text = goal.value.trim();
      if (!text) { toast("Write the goal first", "One or two sentences is enough."); goal.focus(); return; }
      const picked = [...APP.querySelectorAll("input.planner:checked")].map(x => x.value);
      const lv = (APP.querySelector('input[name="level"]:checked') || {}).value;
      act("plan.goal", { goal: text, planners: picked.length ? picked : null, review: lv }, { button: e.currentTarget, title: "Planning started" });
    } }, "Start planning")));
}

/* ---------------------------------------------------------------- work: the board */

function boardColumns(st) {
  const real = st.tasks.filter(t => t.kind !== "epic");
  return [
    { id: "todo", label: "To do", items: real.filter(t => ["open", "ready"].includes(t.status)) },
    { id: "doing", label: "In progress", items: real.filter(t => ["claimed", "changes_requested"].includes(t.status)) },
    { id: "checking", label: "Checking", items: real.filter(t => ["proving", "in_review", "merge_blocked"].includes(t.status)) },
    { id: "done", label: "Done", items: real.filter(t => t.status === "done") },
  ];
}

function cardStatus(t) {
  if (t.status === "open") return t.waits_for.length ? "After " + t.waits_for.join(", ") : "Waiting";
  if (t.status === "in_review") return t.reviewers.length ? "Checked by " + listWords(t.reviewers) : "Being checked";
  return t.status_label;
}

PAGES.work = st => {
  const sel = taskRoute();
  if (sel) return taskPage(st, sel);
  const q = ui.workSearch.trim().toLowerCase();
  const match = t => !q || (t.id + " " + t.title + " " + t.labels.join(" ") + " " + t.owner).toLowerCase().includes(q);
  const cols = boardColumns(st);
  const epics = st.tasks.filter(t => t.kind === "epic" && t.status !== "cancelled");
  const titleOf = id => (st.tasks.find(t => t.id === id) || {}).title || id;
  const backlog = st.tasks.filter(t => t.status === "backlog").length;
  const cancelled = st.tasks.filter(t => t.status === "cancelled");
  const card = t => h("li", null, h("a", { class: "card tone-" + TASK_TONE[t.status], href: "#/work/" + t.id },
    h("span", { class: "card-title", text: t.title }),
    t.parent ? h("span", { class: "card-group", text: titleOf(t.parent) }) : null,
    h("span", { class: "card-meta" }, h("span", { class: "id", text: t.id }),
      t.priority < 2 ? h("span", { class: "tag warn", text: PRIORITY[t.priority] }) : null,
      t.owner ? h("span", { class: "owner", title: t.owner }, h("span", { class: "mini-mono", "aria-hidden": "true", text: monogram(t.owner) }), t.owner) : null,
      ["ready", "claimed", "done"].includes(t.status) ? null : h("span", { class: "card-status", text: cardStatus(t) }))));
  const search = h("input", { type: "search", "data-k": "work-search", placeholder: "Find a task", "aria-label": "Find a task", value: ui.workSearch,
    oninput: e => { ui.workSearch = e.target.value; render(); } });
  const any = st.tasks.some(t => t.status !== "backlog");
  return h("div", { class: "stack" },
    pageHead("Work", any ? `${progress(st).done} of ${plural(progress(st).total, "task")} done.` : null,
      h("button", { type: "button", "aria-expanded": String(!!ui.fileOpen), onclick: () => { ui.fileOpen = !ui.fileOpen; render(); } }, icon("plus", "sm"), "Add a task")),
    ui.fileOpen ? fileForm(st) : null,
    backlog ? h("p", { class: "note you" }, `Your AIs found ${plural(backlog, "more thing")} to do. `, h("a", { href: "#/inbox", text: "Decide in your inbox" })) : null,
    any ? h("div", { class: "toolbar" }, search) : null,
    any ? h("div", { class: "board" }, cols.map(c => {
      let list = c.items.filter(match);
      const total = list.length;
      if (c.id === "done") list = list.slice().reverse();
      if (c.id === "done" && !ui.showAllDone && !q) list = list.slice(0, 8);
      return h("section", { class: "col col-" + c.id, "aria-labelledby": "col-" + c.id },
        h("h2", { id: "col-" + c.id }, h("i", { class: "seg-" + c.id, "aria-hidden": "true" }), c.label, h("span", { class: "n", text: String(total) })),
        list.length ? h("ul", { class: "cards" }, list.map(card)) : h("p", { class: "col-empty", text: { todo: "Nothing waiting.", doing: "No AI is working on a task.", checking: "Nothing is being tested or checked.", done: "Nothing finished yet." }[c.id] }),
        c.id === "done" && total > list.length ? h("button", { class: "quiet", type: "button", onclick: () => { ui.showAllDone = true; render(); } }, `Show all ${total}`) : null);
    })) : h("div", { class: "all-clear" }, h("div", null, h("h2", { text: "No work yet" }),
      h("p", { text: "Tasks appear here when you approve a plan. You can also add one yourself." }))),
    epics.length ? h("details", { class: "fold", "data-k": "epics" }, h("summary", null, icon("chevron", "sm turn"), `Groups of tasks (${epics.length})`),
      h("ul", { class: "rows" }, epics.map(e => { const kids = st.tasks.filter(t => t.parent === e.id); return h("li", null, h("a", { class: "row-link", href: "#/work/" + e.id },
        h("span", { class: "id", text: e.id }), h("span", { class: "grow", text: e.title }), h("span", { class: "faint", text: `${kids.filter(k => k.status === "done").length} of ${kids.length} done` }))); }))) : null,
    cancelled.length ? h("details", { class: "fold", "data-k": "cancelled" }, h("summary", null, icon("chevron", "sm turn"), `Cancelled (${cancelled.length})`),
      h("ul", { class: "rows" }, cancelled.map(t => h("li", null, h("a", { class: "row-link", href: "#/work/" + t.id }, h("span", { class: "id", text: t.id }), h("span", { class: "grow", text: t.title })))))) : null);
};

function fileForm(st) {
  const epics = st.tasks.filter(t => t.kind === "epic" && !["done", "cancelled"].includes(t.status));
  const f = {
    title: h("input", { type: "text", id: "f-title", "data-k": "f-title" }),
    kind: h("select", { id: "f-kind", "data-k": "f-kind" }, ["task", "feature", "bug", "chore", "docs", "test", "epic"].map(k => h("option", { value: k }, k === "epic" ? "group of tasks (epic)" : k))),
    prio: h("select", { id: "f-prio", "data-k": "f-prio" }, [0, 1, 2, 3, 4].map(p => h("option", { value: String(p), selected: p === 2 ? true : null }, PRIORITY[p]))),
    summary: h("textarea", { id: "f-summary", "data-k": "f-summary", rows: "3" }),
    files: h("input", { type: "text", id: "f-files", "data-k": "f-files", placeholder: "src/search.py, tests/test_search.py", spellcheck: "false" }),
    proof: h("input", { type: "text", id: "f-proof", "data-k": "f-proof", placeholder: "python -m pytest -q tests/test_search.py", spellcheck: "false" }),
    labels: h("input", { type: "text", id: "f-labels", "data-k": "f-labels", placeholder: "ui, search" }),
    parent: h("select", { id: "f-parent", "data-k": "f-parent" }, h("option", { value: "" }, "None"), epics.map(e => h("option", { value: e.id }, `${e.id} ${e.title}`))),
  };
  return h("section", { class: "panel" }, h("header", null, h("h2", { text: "Add a task" }),
    h("p", { text: "With files and a test command it is ready at once. Without them it waits in your inbox until you add them." })),
    h("div", { class: "panel-body" }, h("div", { class: "form-grid" },
      h("div", { class: "field wide" }, h("label", { for: "f-title", text: "What needs doing" }), f.title),
      h("div", { class: "field wide" }, h("label", { for: "f-summary", text: "Details (optional)" }), f.summary),
      h("div", { class: "field" }, h("label", { for: "f-files", text: "Files it may change" }), h("span", { class: "help", text: "Separate with commas. Patterns like src/** work." }), f.files),
      h("div", { class: "field" }, h("label", { for: "f-proof", text: "Test command" }), h("span", { class: "help", text: "Runs on your computer when the task is finished." }), f.proof)),
      h("details", { class: "fold", "data-k": "f-more" }, h("summary", null, icon("chevron", "sm turn"), "More options"),
        h("div", { class: "form-grid fold-body" },
          h("div", { class: "field" }, h("label", { for: "f-kind", text: "Kind" }), f.kind),
          h("div", { class: "field" }, h("label", { for: "f-prio", text: "Priority" }), f.prio),
          h("div", { class: "field" }, h("label", { for: "f-labels", text: "Labels" }), f.labels),
          h("div", { class: "field" }, h("label", { for: "f-parent", text: "Part of group" }), f.parent))),
      h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => {
        if (!f.title.value.trim()) { toast("Say what needs doing", ""); f.title.focus(); return; }
        act("task.file", { title: f.title.value.trim(), kind: f.kind.value, priority: Number(f.prio.value), summary: f.summary.value.trim() || null,
          files: csv(f.files.value), proof: f.proof.value.trim() ? [f.proof.value.trim()] : null, labels: csv(f.labels.value), parent: f.parent.value || null },
          { button: e.currentTarget, after: () => { ui.fileOpen = false; } });
      } }, "Add task"), h("button", { class: "quiet", type: "button", onclick: () => { ui.fileOpen = false; render(); } }, "Close"))));
}

function taskPage(st, id) {
  const d = cache.task[id];
  const back = backLink("#/work", "Work");
  if (!d) { loadTask(id).then(render); return h("div", { class: "stack" }, back, h("p", { class: "empty", text: "Loading " + id + "…" })); }
  if (d.ok === false) return h("div", { class: "stack" }, back, h("p", { class: "empty", text: plainText(d.message) || "Not found" }));
  const builders = st.seats.filter(x => x.roles.includes("build") && x.status === "active");
  const top = [];
  if (d.status === "backlog") top.push(h("section", { class: "approve" }, h("p", { class: "eyebrow", text: "Waiting for your OK" }),
    h("h2", { text: d.filed_by && d.filed_by !== "human" ? `${d.filed_by} found this while working` : "You added this" }), acceptForm(d, builders)));
  if (d.status === "merge_blocked") top.push(h("div", { class: "note warn" }, h("p", { text: plainText(d.merge_note) || "Approved, but it can't be merged yet." }),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => act("task.merge", { task: d.id }, { button: e.currentTarget }) }, "Try the merge again"))));
  const sec = (title, ...body) => h("section", { class: "detail-sec" }, h("h2", { text: title }), body);
  return h("div", { class: "stack task-page" },
    back,
    h("div", { class: "page-head" }, h("div", { class: "page-title" },
      h("p", { class: "eyebrow" }, d.id, d.kind !== "task" ? ` · ${d.kind}` : ""),
      h("h1", { text: d.title }),
      h("p", { class: "inline-list" }, chip(d.status_label, TASK_TONE[d.status]), d.priority !== 2 ? h("span", { class: "tag" + (d.priority < 2 ? " warn" : ""), text: PRIORITY[d.priority] + " priority" }) : null,
        d.labels.map(l => h("span", { class: "tag", text: l }))))),
    top,
    h("div", { class: "detail-grid" },
      h("div", { class: "stack" },
        d.summary ? h("p", { class: "pre prose", text: plainText(d.summary) }) : null,
        d.proofs.length ? sec("Test runs", d.proofs.slice(0, 3).map(p => h("div", { class: "stack-sm" },
          h("p", { class: "inline-list" }, chip({ passed: "Passed", failed: "Failed", running: "Running", queued: "Queued" }[p.status] || p.status, p.status === "passed" ? "ok" : ["running", "queued"].includes(p.status) ? "work" : "stop"), h("span", { class: "faint", text: `${p.at}, for ${p.by}` })),
          p.output ? h("div", { class: "output", text: p.output }) : null))) : null,
        d.checkpoints.length ? sec("Progress notes", h("ul", { class: "rows" }, d.checkpoints.slice(0, 6).map(c => h("li", null,
          h("p", null, h("strong", { text: c.seat + ": " }), c.line), h("p", { class: "faint", text: `${c.at}${c.files.length ? `, ${plural(c.files.length, "file")} +${c.added} -${c.removed}` : ""}` }))))) : null,
        d.reviews.length ? sec("Checks by other AIs", h("ul", { class: "rows" }, d.reviews.map(r => h("li", null,
          h("p", { class: "inline-list" }, h("strong", { text: who(r.reviewer) }), chip(r.verdict === "approve" ? "approved" : r.verdict === "changes" ? "asked for changes" : "checking", r.verdict === "approve" ? "ok" : r.verdict === "changes" ? "warn" : "work"),
            h("span", { class: "faint", text: `${(CHECKING[r.level] || r.level)} checking, round ${r.round}` })),
          r.points.length ? h("ul", { class: "points" }, r.points.map(p => h("li", { text: typeof p === "string" ? p : JSON.stringify(p) }))) : null)))) : null,
        d.comments.length ? sec("Comments on lines", h("ul", { class: "rows" }, d.comments.map(c => h("li", null,
          h("p", { class: "mono small", text: `${c.file}${c.line ? ":" + c.line : ""}` }), h("p", { text: c.text }), c.reply ? h("p", { class: "muted", text: "Reply: " + c.reply }) : null)))) : null,
        d.changed.length ? sec("Files changed", h("ul", { class: "rows" }, d.changed.map(c => h("li", { class: "mono small" }, c.path, h("span", { class: "faint", text: `  +${c.added} -${c.removed}` }))))) : null,
        d.events.length ? sec("History", feed(d.events)) : null),
      h("aside", { class: "stack" },
        h("section", { class: "panel" }, h("div", { class: "panel-body" }, h("dl", { class: "kv" },
          h("dt", { text: "Who" }), h("dd", { text: d.owner || "whichever AI is free" }),
          d.filed_by ? [h("dt", { text: "Added by" }), h("dd", { text: who(d.filed_by) })] : null,
          h("dt", { text: "Checking" }), h("dd", { text: CHECKING[d.review] || d.review }),
          h("dt", { text: "Files" }), h("dd", { class: "mono small", text: d.files.join(", ") || "-" }),
          h("dt", { text: "Tested by" }), h("dd", { class: "mono small", text: d.proof.join(" && ") || "-" }),
          d.waits_for.length ? [h("dt", { text: "After" }), h("dd", null, d.waits_for.map(x => h("a", { class: "id", href: "#/work/" + x, text: x + " " })))] : null,
          d.links.filter(l => l.kind !== "waits_for").length ? [h("dt", { text: "Linked" }), h("dd", null, d.links.filter(l => l.kind !== "waits_for").map(l => h("span", null, l.kind.replace(/_/g, " ") + " ", h("a", { class: "id", href: "#/work/" + l.other, text: l.other }), " ")))] : null,
          d.parent ? [h("dt", { text: "Group" }), h("dd", null, h("a", { class: "id", href: "#/work/" + d.parent, text: d.parent }))] : null),
          d.children.length ? h("ul", { class: "rows" }, d.children.map(c => h("li", null, h("a", { class: "row-link", href: "#/work/" + c.id }, h("span", { class: "id", text: c.id }), h("span", { class: "grow", text: c.title }))))) : null)),
        h("details", { class: "fold panel-fold", "data-k": "change-" + d.id }, h("summary", null, icon("chevron", "sm turn"), "Change this task"),
          taskControls(st, d, builders), ui.editOpen === d.id ? editForm(d) : null))));
}

function taskControls(st, d, builders) {
  if (["done", "cancelled"].includes(d.status)) return h("p", { class: "faint", text: "Finished tasks cannot be changed." });
  const reviewSel = h("select", { id: "t-check", onchange: e => act("task.set_review", { task: d.id, level: e.target.value }) },
    ["default", "low", "mid", "high"].map(v => h("option", { value: v, selected: v === "default" ? true : null }, v === "default" ? `Project default (${CHECKING[st.project.review]})` : CHECKING[v])));
  const ownerSel = h("select", { id: "t-owner", onchange: e => act("task.reassign", { task: d.id, owner: e.target.value || null }) },
    h("option", { value: "" }, "Whichever AI is free"), builders.map(x => h("option", { value: x.handle, selected: x.handle === d.owner ? true : null }, x.handle)));
  const confirmKey = "cancel-" + d.id;
  const reason = h("input", { type: "text", "data-k": "cancel-task-" + d.id, placeholder: "Why", "aria-label": "Reason for cancelling" });
  return h("div", { class: "stack fold-body" },
    h("div", { class: "field" }, h("label", { for: "t-owner", text: "Who does it" }), ownerSel),
    h("div", { class: "field" }, h("label", { for: "t-check", text: "How carefully it is checked" }), reviewSel),
    h("div", { class: "btn-row" },
      h("button", { type: "button", onclick: () => { ui.editOpen = ui.editOpen === d.id ? false : d.id; render(); } }, "Edit details"),
      h("button", { type: "button", onclick: () => { ui.linkOpen = ui.linkOpen === d.id ? false : d.id; render(); } }, icon("link", "sm"), "Link"),
      ui.confirm[confirmKey] ? null : h("button", { class: "danger", type: "button", onclick: () => { ui.confirm[confirmKey] = true; render(); } }, "Cancel task…")),
    ui.linkOpen === d.id ? linkForm(st, d) : null,
    ui.confirm[confirmKey] ? h("div", { class: "btn-row" }, reason, h("button", { class: "danger solid", type: "button", onclick: e => {
      if (!reason.value.trim()) { toast("Add a reason", "The AI working on it reads it."); return; }
      act("task.cancel", { task: d.id, reason: reason.value.trim() }, { button: e.currentTarget, after: () => { ui.confirm[confirmKey] = false; } });
    } }, "Cancel task"), h("button", { type: "button", onclick: () => { ui.confirm[confirmKey] = false; render(); } }, "Keep it")) : null);
}

function linkForm(st, d) {
  const rel = h("select", { "aria-label": "Relation", "data-k": "link-rel" },
    [["waits_for", "waits for"], ["related", "is related to"], ["discovered_from", "was found while doing"], ["parent", "is part of group"]].map(([v, l]) => h("option", { value: v }, l)));
  const other = h("select", { "aria-label": "Other task", "data-k": "link-other" }, st.tasks.filter(t => t.id !== d.id).map(t => h("option", { value: t.id }, `${t.id} ${fit(t.title, 40)}`)));
  return h("div", { class: "btn-row" }, h("span", { class: "id", text: d.id }), rel, other,
    h("button", { class: "primary", type: "button", onclick: e => act("task.link", { task: d.id, relation: rel.value, other: other.value }, { button: e.currentTarget, after: () => { ui.linkOpen = false; } }) }, "Add link"));
}

function editForm(d) {
  const early = ["backlog", "open", "ready"].includes(d.status);
  const t = h("input", { type: "text", id: "e-title", "data-k": "e-title-" + d.id, value: d.title });
  const p = h("select", { id: "e-prio", "data-k": "e-prio-" + d.id }, [0, 1, 2, 3, 4].map(n => h("option", { value: String(n), selected: n === d.priority ? true : null }, PRIORITY[n])));
  const l = h("input", { type: "text", id: "e-labels", "data-k": "e-labels-" + d.id, value: d.labels.join(", ") });
  const f = h("input", { type: "text", id: "e-files", "data-k": "e-files-" + d.id, value: d.files.join(", "), disabled: !early });
  const c = h("input", { type: "text", id: "e-proof", "data-k": "e-proof-" + d.id, value: d.proof.join(" && "), disabled: !early });
  return h("div", { class: "stack" },
    h("div", { class: "form-grid" },
      h("div", { class: "field wide" }, h("label", { for: "e-title", text: "Title" }), t),
      h("div", { class: "field" }, h("label", { for: "e-prio", text: "Priority" }), p),
      h("div", { class: "field" }, h("label", { for: "e-labels", text: "Labels" }), l),
      h("div", { class: "field wide" }, h("label", { for: "e-files", text: "Files" }), early ? null : h("span", { class: "help", text: "Fixed once work has started." }), f),
      h("div", { class: "field wide" }, h("label", { for: "e-proof", text: "Test command" }), c)),
    h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => {
      const params = { task: d.id, title: t.value.trim(), priority: Number(p.value), labels: csv(l.value) || [] };
      if (early) { params.files = csv(f.value) || []; params.proof = cmds(c.value); }
      act("task.edit", params, { button: e.currentTarget, after: () => { ui.editOpen = false; } });
    } }, "Save changes")));
}

/* ---------------------------------------------------------------- team */

const APP_GROUPS = [
  ["terminal", "In a terminal", "terminal", "Opens in a new terminal window, already connected."],
  ["editor", "In a code editor", "code", "Opens the right folder in VS Code or Cursor; you send one message."],
  ["desktop", "In a desktop app", "desktop", "The Claude or ChatGPT app. Connect it once."],
  ["manual", "Something else", "plus", "Any app that supports MCP. You add one setting yourself."],
];
const APP_NAMES = {
  "claude-code": ["Claude Code", "Anthropic"], "claude-vscode": ["Claude Code", "in VS Code"], "claude-app": ["Claude app", "Plans and checks only"],
  "codex-cli": ["Codex", "OpenAI"], "codex-vscode": ["Codex", "in VS Code"], "codex-app": ["ChatGPT app", "Codex mode"],
  "gemini-cli": ["Gemini CLI", "Google"], "qwen-code": ["Qwen Code", "Alibaba"], "opencode": ["opencode", "any model"],
  "copilot-cli": ["Copilot CLI", "GitHub"], "cursor": ["Cursor", "any model"], "other": ["Another app", "with MCP support"],
};
const groupOf = a => a.start === "vscode" || a.start === "editor" ? "editor" : a.start;

PAGES.team = st => {
  if (route.sub === "add") return addPicker(st, route.parts[1]);
  const sel = route.sub;
  return h("div", { class: "stack" },
    pageHead("Team", st.seats.length ? `${plural(st.seats.length, "AI model")} working on this project.` : null,
      h("a", { class: "btn primary", href: "#/team/add" }, icon("plus", "sm"), "Add an AI model")),
    st.seats.length ? h("ul", { class: "seats" }, st.seats.map(x => seatCard(st, x, x.handle === sel)))
      : h("div", { class: "all-clear" }, h("div", null, h("h2", { text: "No AIs yet" }),
        h("p", { text: "Add two or more, ideally from different companies, so they check each other's work." }))),
    h("details", { class: "fold", "data-k": "connect" }, h("summary", null, icon("chevron", "sm turn"), "Connect apps you open yourself"), connectPanel(st)));
};

function seatCard(st, x, highlight) {
  const [cls, note] = seatState(x);
  const started = ui.started[x.handle];
  const start = x.start;
  const notJoined = !x.joined_ever;
  const startBtn = x.status !== "active" ? null : start.kind === "terminal"
    ? h("button", { class: x.live ? "" : "primary", type: "button", disabled: x.live ? true : null, title: x.live ? "Already at the table" : null, onclick: e => startSeat(x, e.currentTarget) }, icon("terminal", "sm"), x.live ? "Running" : "Start in a terminal")
    : start.kind === "vscode" ? h("button", { class: notJoined ? "primary" : "", type: "button", onclick: e => startSeat(x, e.currentTarget) }, icon("code", "sm"), "Open in VS Code")
      : start.kind === "editor" ? h("button", { class: notJoined ? "primary" : "", type: "button", onclick: e => startSeat(x, e.currentTarget) }, icon("code", "sm"), "Open in " + x.app_label.replace(" editor", ""))
        : h("button", { class: notJoined ? "primary" : "", type: "button", onclick: () => { ui.started[x.handle] = { steps: start.steps, join: start.join }; render(); } }, "Show how to start it");
  const more = [];
  if (x.status === "paused") more.push(h("button", { type: "button", onclick: e => act("seat.resume", { handle: x.handle }, { button: e.currentTarget }) }, "Resume"));
  else more.push(h("button", { type: "button", onclick: e => act("seat.pause", { handle: x.handle }, { button: e.currentTarget }) }, "Pause"));
  if (x.live) more.push(h("button", { type: "button", title: "Use this if you closed its chat window and want to start it again", onclick: e => act("seat.release", { handle: x.handle }, { button: e.currentTarget }) }, "Disconnect its old chat"));
  if (x.worktree) more.push(h("button", { type: "button", onclick: e => special("folder", { path: x.worktree }, { button: e.currentTarget }) }, icon("folder", "sm"), "Open its folder"));
  const rmKey = "rm-" + x.handle;
  more.push(ui.confirm[rmKey]
    ? h("button", { class: "danger solid", type: "button", onclick: e => act("seat.remove", { handle: x.handle }, { button: e.currentTarget, after: () => { ui.confirm[rmKey] = false; } }) }, "Yes, remove " + x.handle)
    : h("button", { class: "danger", type: "button", onclick: () => { ui.confirm[rmKey] = true; render(); setTimeout(() => { ui.confirm[rmKey] = false; render(); }, 5000); } }, "Remove…"));
  const jobs = ["plan", "build", "review"].filter(r => x.roles.includes(r)).map(r => ({ plan: "plans", build: "builds", review: "checks work" }[r]));
  return h("li", { class: "seat-card" + (highlight ? " highlight" : ""), id: "seat-" + x.handle },
    h("div", { class: "seat-id" }, h("span", { class: "mono-disc " + cls, "aria-hidden": "true", text: monogram(x.handle) }),
      h("div", null, h("h2", { text: x.handle }), h("p", { class: "faint", text: `${x.model} · ${x.app_label}` }))),
    h("div", { class: "seat-state" }, h("p", null, h("span", { class: "state-dot " + cls, "aria-hidden": "true" }), h("strong", { text: note })),
      h("p", { class: "faint", text: capital(listWords(jobs)) + "." + (x.roles.includes("build") ? "" : " Cannot edit files.") })),
    h("div", { class: "seat-actions" }, h("div", { class: "btn-row" }, startBtn,
      h("details", { class: "menu", "data-k": "menu-" + x.handle }, h("summary", { class: "btn quiet", "aria-label": "More for " + x.handle }, icon("more")), h("div", { class: "menu-body" }, more)))),
    started ? h("div", { class: "seat-started" }, startedBox(x, started)) : null);
}

async function startSeat(x, btn) {
  const res = await special("start", { handle: x.handle }, { button: btn, silent: true });
  if (res.ok) { ui.started[x.handle] = { text: res.text, join: res.join, steps: res.steps }; toast(capital(res.text), x.start.kind === "terminal" ? "Approve the Roundtable tools when the app asks." : ""); }
  else { ui.started[x.handle] = { error: res.message, hint: res.hint, command: res.command, folder: res.folder, join: x.start.join, steps: x.start.steps }; toast(plainText(res.message) || "Could not start it", plainText(res.hint || ""), { error: true }); }
  render();
}

function startedBox(x, info) {
  return h("div", { class: "note" + (info.error ? " warn" : "") },
    info.error ? h("p", null, h("strong", { text: plainText(info.error) })) : null,
    info.command ? [h("p", { class: "small", text: "Run this in a terminal instead:" }), copyBox(`cd ${info.folder || ""} && ${info.command}`.replace(/^cd  && /, ""))] : null,
    info.steps && info.steps.length ? h("ol", { class: "points" }, info.steps.map(s => h("li", { text: s }))) : null,
    info.join ? [h("p", { class: "small", text: "Then send this message in its chat:" }), copyBox(info.join)] : null);
}

function suggestName(st, app, model) {
  const taken = new Set(st.seats.map(x => x.handle));
  const skip = ["claude", "gpt", "gemini", "qwen", "models", "model"];
  const fromModel = String(model || "").toLowerCase().split(/[-_.\/ ]+/).find(x => /^[a-z]{2,}$/.test(x) && !skip.includes(x));
  const base = fromModel || { "gemini-cli": "gemini", "qwen-code": "qwen", opencode: "opencode", "copilot-cli": "copilot", cursor: "cursor", "codex-cli": "codex", "codex-vscode": "codex", "codex-app": "codex" }[app.key] || "helper";
  let name = base, i = 2;
  while (taken.has(name)) name = base + i++;
  return name;
}

function addPicker(st, appKey) {
  const app = st.apps.find(a => a.key === appKey);
  const steps = h("ol", { class: "wizard-steps", "aria-label": "Steps" },
    h("li", { class: app ? "past" : "now", "aria-current": app ? null : "step" }, app ? h("a", { href: "#/team/add", text: "1. Where it works" }) : "1. Where it works"),
    h("li", { class: app ? "now" : "", "aria-current": app ? "step" : null, text: "2. Name and model" }));
  if (!app) {
    return h("div", { class: "stack" }, backLink("#/team", "Team"),
      pageHead("Add an AI model", "It uses your own subscription in its own app. No API keys."), steps,
      APP_GROUPS.map(([g, label, ic, help]) => {
        const list = st.apps.filter(a => groupOf(a) === g);
        if (!list.length) return null;
        return h("section", { class: "tile-group", "aria-labelledby": "tg-" + g },
          h("div", { class: "tile-head" }, icon(ic), h("div", null, h("h2", { id: "tg-" + g, text: label }), h("p", { class: "faint", text: help }))),
          h("ul", { class: "tiles" }, list.map(a => {
            const [name, sub] = APP_NAMES[a.key] || [a.label, ""];
            return h("li", null, h("a", { class: "tile", href: "#/team/add/" + a.key },
              h("strong", { text: name }), h("span", { class: "faint", text: sub }),
              !a.coding ? h("span", { class: "tile-note", text: "Can't edit files" }) : null));
          })));
      }));
  }
  const [appName, appSub] = APP_NAMES[app.key] || [app.label, ""];
  const suggestions = app.company ? (st.models[app.company] || []) : Object.values(st.models).flat();
  const defModel = app.company && suggestions[0] ? suggestions[0] : "";
  const model = h("input", { type: "text", id: "m-model", "data-k": "m-model-" + app.key, list: "m-models", autocomplete: "off", spellcheck: "false", value: defModel, placeholder: defModel ? null : "the model name the app uses" });
  const name = h("input", { type: "text", id: "m-name", "data-k": "m-name-" + app.key, autocomplete: "off", spellcheck: "false", value: suggestName(st, app, defModel), maxlength: "24" });
  const dl = h("datalist", { id: "m-models" }, suggestions.map(m => h("option", { value: m })));
  const company = h("select", { id: "m-company", "data-k": "m-company-" + app.key }, h("option", { value: "" }, app.company ? `${capital(app.company)} (from the app)` : "Work it out from the model name"), st.companies.map(c => h("option", { value: c }, capital(c))));
  const roles = ["plan", "build", "review"].map(r => h("input", { type: "checkbox", value: r, checked: r !== "build" || app.coding, disabled: r === "build" && !app.coding ? true : null, "data-k": "m-role-" + r, class: "m-role" }));
  const how = {
    terminal: "Roundtable gives it its own copy of your project and opens it in a terminal window, already connected.",
    vscode: "Roundtable gives it its own copy of your project. You open that folder in VS Code and send one message to connect it.",
    editor: "Roundtable gives it its own copy of your project with the connection already set. Open that folder in the editor and send one message.",
    desktop: app.coding ? "Connect the app once (on the Team page), open the AI's folder in it, and send one message." : "This app can't edit files, so it plans and checks others' work. Connect it once and send one message.",
    manual: "You add Roundtable to the app's MCP settings yourself; its card on the Team page shows exactly what to enter.",
  }[app.start] || "";
  return h("div", { class: "stack" }, backLink("#/team/add", "Choose another app"),
    pageHead("Add an AI model", null), steps,
    h("section", { class: "panel" }, h("div", { class: "panel-body stack" },
      h("div", { class: "chosen" }, h("div", null, h("p", { class: "eyebrow", text: "Works in" }), h("p", null, h("strong", { text: appName }), " ", h("span", { class: "faint", text: appSub }))),
        h("a", { href: "#/team/add", text: "Change" })),
      h("p", { class: "muted", text: how }),
      h("div", { class: "form-grid" },
        h("div", { class: "field" }, h("label", { for: "m-name", text: "Its name" }), h("span", { class: "help", text: "Short, lowercase. The AIs use it to talk to each other." }), name),
        h("div", { class: "field" }, h("label", { for: "m-model", text: "Model" }), h("span", { class: "help", text: app.company ? "Already filled in. Change it if you use another one." : "The model name the app uses, like claude-opus-5-5." }), model, dl),
        !app.company ? h("div", { class: "field" }, h("label", { for: "m-company", text: "Made by" }), h("span", { class: "help", text: "Work is checked by an AI from another company when there is one." }), company) : null),
      h("details", { class: "fold", "data-k": "m-adv-" + app.key }, h("summary", null, icon("chevron", "sm turn"), "Advanced options"),
        h("div", { class: "fold-body stack" },
          app.company ? h("div", { class: "field" }, h("label", { for: "m-company", text: "Made by" }), company) : null,
          h("fieldset", { class: "field" }, h("legend", { text: "What it does" }), h("div", { class: "choices row" },
            h("label", { class: "check" }, roles[0], h("span", null, "Writes plans")), h("label", { class: "check" }, roles[1], h("span", null, "Builds")), h("label", { class: "check" }, roles[2], h("span", null, "Checks others' work")))))),
      h("div", { class: "btn-row" }, h("button", { class: "primary big", type: "button", onclick: e => {
        const handle = name.value.trim().toLowerCase();
        const m = model.value.trim();
        if (!/^[a-z][a-z0-9_-]{1,23}$/.test(handle)) { toast("Pick another name", "2 to 24 letters, digits, - or _, starting with a letter. For example opus or sol."); name.focus(); return; }
        if (!m) { toast("Which model?", "Type the model name the app uses."); model.focus(); return; }
        act("seat.add", { handle, model: m, app: app.key, company: company.value || null, roles: roles.filter(r => r.checked).map(r => r.value) },
          { button: e.currentTarget, title: "Added " + handle, after: () => go("#/team/" + handle) });
      } }, "Add this AI"), h("a", { class: "btn quiet", href: "#/team" }, "Cancel")))));
}

function connectPanel(st) {
  const c = st.project.connected;
  const items = [
    ["claude-code", "Claude Code (project settings)", "Only needed if you open Claude Code yourself instead of using Start. Writes .mcp.json in the project folder."],
    ["claude-app", "Claude desktop app", "Lets a Claude desktop chat join. Restart the app afterwards."],
    ["codex", "Codex: terminal, VS Code and the ChatGPT app", "One entry in ~/.codex/config.toml serves all three. Restart them afterwards."],
    ["copilot", "GitHub Copilot CLI", "Adds Roundtable to ~/.copilot/mcp-config.json."],
  ];
  return h("div", { class: "fold-body" }, h("p", { class: "muted", text: "AIs you start from this page are connected automatically. These are for apps you open yourself. Roundtable adds its entry to each settings file and keeps a backup." }),
    h("ul", { class: "rows" }, items.map(([key, label, help]) => h("li", null,
      h("p", { class: "inline-list" }, h("strong", { text: label }), c[key] ? chip("connected", "ok") : chip("not connected", "idle")),
      h("p", { class: "faint", text: help }),
      ui.preview[key] ? h("div", { class: "output", text: ui.preview[key] }) : null,
      h("div", { class: "btn-row" },
        h("button", { type: "button", onclick: async e => { const r = await special("connect", { app: key, preview: true }, { button: e.currentTarget, silent: true }); ui.preview[key] = r.ok ? r.text : (r.message + (r.hint ? "\n" + r.hint : "")); render(); } }, "Preview the change"),
        h("button", { class: c[key] ? "" : "primary", type: "button", onclick: e => special("connect", { app: key }, { button: e.currentTarget, title: "Connected", after: () => { delete ui.preview[key]; } }) }, c[key] ? "Update" : "Connect"),
        c[key] ? h("button", { class: "quiet", type: "button", onclick: e => special("connect", { app: key, remove: true }, { button: e.currentTarget, title: "Disconnected" }) }, "Disconnect") : null)))));
}

/* ---------------------------------------------------------------- more */

PAGES.more = st => {
  const theme = store("rt.theme") || "auto";
  return h("div", { class: "stack" },
    pageHead("More", null),
    h("ul", { class: "more-list" }, NAV_MORE.map(([id, label, ic, desc]) => h("li", null, h("a", { href: "#/" + id }, icon(ic),
      h("span", null, h("strong", { text: label }), h("small", { text: desc })), icon("chevron", "sm")))),
      h("li", null, h("a", { href: "#/switch" }, icon("folder"), h("span", null, h("strong", { text: "Open another project" }), h("small", { text: st.project.root })), icon("chevron", "sm")))),
    h("div", { class: "btn-row" }, h("button", { type: "button", onclick: cycleTheme }, icon(theme === "dark" ? "moon" : "sun", "sm"), "Theme: " + capital(theme)),
      h("span", { class: "faint", text: "Roundtable v" + st.project.version })));
};

/* ---------------------------------------------------------------- usage */

PAGES.usage = st => {
  const warn = (st.config.find(c => c.key === "usage.warn_percent") || { value: 90 }).value;
  return h("div", { class: "stack" },
    pageHead("Usage", "How much each AI has used, as its own app reports it."),
    st.seats.length ? h("div", { class: "seat-usage" }, st.seats.map(x => usageCard(x, warn))) : panel(null, null, h("p", { class: "empty", text: "Add AIs to see their usage." })),
    h("details", { class: "fold", "data-k": "usage-src" }, h("summary", null, icon("chevron", "sm turn"), "Where these numbers come from"), h("div", { class: "prose small fold-body" },
      h("p", { text: "Claude Code started from Roundtable reports how full its chat is, its tokens and the 5-hour and weekly limits. Codex (terminal, VS Code and ChatGPT app) writes them to its session logs, which Roundtable reads. Other apps do not share this, so only Roundtable's own messages are shown for them." }),
      h("p", { text: `Roundtable's tool descriptions cost about ${num(st.overhead_tokens)} tokens once per chat. Message tokens are estimated from characters (about 4 per token).` }))));
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
  return h("section", { class: "panel" }, h("header", null, h("h2", { text: x.handle }), h("p", { text: `${x.model}, ${x.app_label}` })),
    h("div", { class: "panel-body stack" },
      u.snapshot ? h("div", null,
        meter("Chat", snap.context_pct, snap.context_size ? `of ${Math.round(snap.context_size / 1000)}k tokens` : "", warnAt),
        meter("5 hours", snap.limit_5h && snap.limit_5h.pct, snap.limit_5h && resets(snap.limit_5h.resets_at), warnAt),
        meter("Week", snap.limit_7d && snap.limit_7d.pct, snap.limit_7d && resets(snap.limit_7d.resets_at), warnAt))
        : h("p", { class: "no-data", text: ["claude-code", "codex-cli", "codex-vscode", "codex-app"].includes(x.app)
          ? "No numbers yet. They appear after its first reply" + (x.app === "claude-code" ? " when it is started from Roundtable." : ".")
          : "This app does not share how much it has used." }),
      h("dl", { class: "kv" },
        h("dt", { text: "This chat" }), h("dd", { text: snap.session_tokens ? num(snap.session_tokens) + " tokens" : "not reported by this app" }),
        snap.limit_5h ? [h("dt", { text: "5-hour limit" }), h("dd", { text: resets(snap.limit_5h.resets_at) || "-" })] : null,
        snap.limit_7d ? [h("dt", { text: "Weekly limit" }), h("dd", { text: resets(snap.limit_7d.resets_at) || "-" })] : null,
        h("dt", { text: "Roundtable" }), h("dd", { text: `${num(ex.calls)} messages, about ${num(ex.tokens)} tokens (${num(ex.tokens_today)} today)` }))));
}

/* ---------------------------------------------------------------- notes */

PAGES.notes = st => {
  const text = h("textarea", { id: "mem-text", "data-k": "mem-text", rows: "3", placeholder: "Tests need DATABASE_URL set; use the sqlite one in tests/.env" });
  const tags = h("input", { type: "text", id: "mem-tags", "data-k": "mem-tags", placeholder: "tests" });
  const list = st.memories.length ? h("ul", { class: "rows" }, st.memories.map(m => h("li", null,
    h("p", { class: "inline-list" }, m.pinned ? chip("pinned", "you") : null, h("span", { class: "faint", text: `${who(m.author)}, ${m.at}` }), m.tags.map(t => h("span", { class: "tag", text: t }))),
    h("p", { class: "pre", text: m.text }),
    h("div", { class: "btn-row" },
      h("button", { class: "quiet", type: "button", onclick: e => act("memory.pin", { id: m.id, pinned: !m.pinned }, { button: e.currentTarget }) }, icon("pin", "sm"), m.pinned ? "Unpin" : "Pin"),
      h("button", { class: "quiet", type: "button", onclick: e => act("memory.forget", { id: m.id, reason: "removed from the dashboard" }, { button: e.currentTarget }) }, "Delete"))))) :
    h("p", { class: "empty", text: "No notes yet. The AIs add notes as they learn things about the project; you can too." });
  return h("div", { class: "stack" },
    pageHead("Notes", "Things every AI reads when it joins."),
    h("div", { class: "grid-2" }, panel(null, `${plural(st.memories.length, "note")}. Notes written by AIs are shown to the other AIs as information, never as instructions.`, list),
      panel("Add a note", "Your notes are pinned to the top.",
        h("div", { class: "field" }, h("label", { for: "mem-text", text: "Note (60 words at most)" }), text),
        h("div", { class: "field" }, h("label", { for: "mem-tags", text: "Tags (optional)" }), tags),
        h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: e => {
          if (!text.value.trim()) { toast("Write the note first", ""); text.focus(); return; }
          act("memory.add", { text: text.value.trim(), tags: csv(tags.value) }, { button: e.currentTarget, title: "Saved", after: () => { text.value = ""; tags.value = ""; } });
        } }, "Save note")))));
};

/* ---------------------------------------------------------------- history */

PAGES.history = st => {
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
    pageHead("History", "Everything that happened, newest first."),
    h("form", { class: "toolbar", role: "search", onsubmit: e => { e.preventDefault(); run(false); } }, q, task,
      h("button", { type: "submit" }, icon("search", "sm"), "Search"),
      key ? h("button", { class: "quiet", type: "button", onclick: () => { cache.log = null; cache.logKey = ""; render(); } }, "Clear") : null),
    feed(events, { full: true }),
    events.length >= 80 ? h("div", { class: "btn-row" }, h("button", { type: "button", onclick: () => run(true) }, "Show older")) : null);
};

/* ---------------------------------------------------------------- settings */

const MAIN_SECTIONS = ["review", "proof", "git", "watch", "usage", "project"];
const SECTION_LABEL = { project: "Project", review: "Checking each other's work", leases: "File locks", seats: "AIs", proof: "Tests", planning: "Planning", limits: "Limits",
  git: "Git", watch: "Notifications", usage: "Usage", dashboard: "Dashboard", history: "History" };
const SETTING_TEXT = {
  "project.name": ["Project name", "Shown here and to the AIs."],
  "project.main_branch": ["Branch finished work goes into", "Detected when Roundtable was set up."],
  "review.level": ["How carefully the AIs check each other", "Light: tests only. Standard: an AI from another company skims every change. Thorough: two AIs read every line."],
  "review.always_high": ["Always check these files thoroughly", "Comma-separated patterns, like auth/**."],
  "review.max_diff_lines": ["Large change (lines)", "With Standard checking, bigger changes get a summary check and also come to you."],
  "review.spot_check_every": ["Read 1 task in N in full", "With Standard checking."],
  "review.max_rounds": ["Rounds of fixes before it comes to you", "If the AIs keep disagreeing about a change."],
  "proof.timeout_seconds": ["Stop a test run after (seconds)", ""],
  "proof.wait_seconds": ["Wait for tests before answering (seconds)", "Longer runs carry on in the background."],
  "proof.output_lines": ["Lines of test output to keep", ""],
  "git.worktrees": ["Give each coding AI its own copy of the project", "Recommended. Your own folder is never edited by the AIs."],
  "git.worktree_dir": ["Where those copies go", "Empty: next to your project folder."],
  "git.auto_merge": ["Merge finished work automatically", "Into your branch, once it passes its tests and is checked."],
  "watch.notify": ["Desktop notifications", "For serious problems and stuck work, while rt watch runs."],
  "usage.warn_percent": ["Warn me at this % of a plan limit", ""],
};

PAGES.settings = st => {
  const sections = {};
  st.config.forEach(c => (sections[c.section] = sections[c.section] || []).push(c));
  const doc = cache.doctor;
  return h("div", { class: "stack" },
    pageHead("Settings", "Changes save at once. The AIs cannot change these."),
    h("div", { class: "grid-2" },
      h("div", { class: "stack" }, Object.entries(sections).filter(([sec]) => MAIN_SECTIONS.includes(sec)).map(([sec, items]) => panel(SECTION_LABEL[sec] || sec, null, items.map(settingRow))),
        h("details", { class: "fold", "data-k": "more-settings" }, h("summary", null, icon("chevron", "sm turn"), "More settings: limits, planning, file locks, history"),
          h("div", { class: "stack fold-body" }, Object.entries(sections).filter(([sec]) => !MAIN_SECTIONS.includes(sec)).map(([sec, items]) => panel(SECTION_LABEL[sec] || sec, null, items.map(settingRow)))))),
      h("div", { class: "stack" },
        panel("Check the setup", "Looks at git, the AIs' copies of the project, app connections and the commit guard.",
          h("div", { class: "btn-row" }, h("button", { class: "primary", type: "button", onclick: async e => { busy(e.currentTarget, true); cache.doctor = await getJSON("/api/doctor"); busy(e.currentTarget, false); render(); } }, doc ? "Check again" : "Run the checks")),
          doc ? h("ul", { class: "rows" }, doc.items.map(it => h("li", null, h("p", { class: "inline-list" }, chip(it.status === "ok" ? "ok" : it.status === "warn" ? "check" : "problem", it.status === "ok" ? "ok" : it.status === "warn" ? "warn" : "stop"), h("span", { text: it.message })),
            it.fix ? h("p", { class: "faint" }, "Fix: ", h("span", { class: "mono", text: it.fix })) : null))) : null),
        panel("Housekeeping", null,
          h("p", { class: "faint", text: "Tidying keeps each finished task's outcome and drops step-by-step detail older than the History setting." }),
          h("div", { class: "btn-row" }, h("button", { type: "button", onclick: e => act("admin.compact", {}, { button: e.currentTarget }) }, "Tidy old history"),
            h("button", { type: "button", onclick: e => act("admin.export", {}, { button: e.currentTarget }) }, "Export a snapshot"))))));
};

function settingRow(c) {
  const id = "cfg-" + c.key.replace(".", "-");
  const save = v => act("admin.config_set", { key: c.key, value: v }, { title: "Saved" });
  const [label, desc] = SETTING_TEXT[c.key] || [capital(c.key.split(".")[1].replace(/_/g, " ")), c.desc];
  let control;
  if (c.type === "switch") control = h("input", { type: "checkbox", id, checked: c.value, onchange: e => save(e.target.checked ? "true" : "false") });
  else if (c.type === "choice") control = h("select", { id, onchange: e => save(e.target.value) }, c.choices.map(o => h("option", { value: o, selected: o === c.value ? true : null }, c.key === "review.level" ? CHECKING[o] : o)));
  else if (c.type === "number") control = h("input", { type: "number", id, "data-k": id, min: "0", value: String(c.value), onchange: e => save(e.target.value) });
  else if (c.type === "list") control = h("input", { type: "text", id, "data-k": id, value: (c.value || []).join(", "), onchange: e => save(JSON.stringify(csv(e.target.value) || [])) });
  else control = h("input", { type: "text", id, "data-k": id, value: c.value, onchange: e => save(e.target.value) });
  return c.type === "switch"
    ? h("div", { class: "field" }, h("label", { class: "check", for: id }, control, h("span", null, label, desc ? h("small", { text: desc }) : null)))
    : h("div", { class: "field" }, h("label", { for: id, text: label }), desc ? h("span", { class: "help", text: desc }) : null, control);
}

/* ---------------------------------------------------------------- help */

PAGES.help = st => h("div", { class: "stack" },
  pageHead("Help", "How Roundtable works, in plain words."),
  h("div", { class: "grid-2" },
    h("div", { class: "stack" },
      panel("How it works", null, h("div", { class: "prose" },
        h("p", { text: "Several AI models work on one project together. Each runs in its own app (Claude Code, Codex, VS Code, a desktop app) with your own subscription. They coordinate through Roundtable instead of talking in one chat, and you make the decisions." }),
        h("ol", { class: "steps" }, [
          ["Add AI models", "On Team. Two or more, ideally from different companies, so they check each other."],
          ["Start them", "Start opens a terminal or editor in the AI's own copy of your project, already connected."],
          ["Give a goal", "On Plan. Say what to build and how carefully they should check each other."],
          ["They plan", "Each AI writes a plan without seeing the others, then comments on the others' plans without knowing who wrote them. One AI combines the best parts and the others agree."],
          ["Approve the plan", "You read the tasks and the test commands that will run on your computer, and approve. Nothing is built before you do."],
          ["They build", "Each task's files belong to one AI while it works. When it says it is done, Roundtable runs the tests itself, another AI checks the changes, and the work is merged into your project."],
        ].map(([t, d]) => h("li", null, h("div", null, h("strong", { text: t }), h("small", { text: d }))))),
        h("p", { text: "AIs do not listen in the background: when a chat goes quiet, type \"check roundtable\" in it. Running rt watch sends you desktop notifications when something needs you." }))),
      panel("Words you may see in the AIs' chats", null, h("dl", { class: "kv glossary" }, [
        ["Seat", "One AI in one app, with a short name like opus."],
        ["Working copy", "The AI's own folder with a copy of your project, on its own git branch. Your folder is never edited by the AIs."],
        ["Lease", "While an AI works on a task, that task's files are locked to it. Others can read them and suggest changes, not edit."],
        ["Proof", "The test command that shows a task works. Roundtable runs it; an AI saying \"done\" is not enough."],
        ["Review depth", "How carefully they check each other: low is Light, mid is Standard, high is Thorough."],
        ["Lock", "Approving the plan."],
        ["Backlog", "Work an AI found while doing something else. It waits in your inbox for your OK."],
        ["Epic", "A group of tasks; done when they all are."],
        ["Memory", "The notes every AI reads when it joins."],
        ["Alert levels", "1 note, 2 heads-up, 3 the AIs it affects must acknowledge, 4 holds the files, 5 freezes them and stops everyone."],
      ].map(([t, d]) => [h("dt", { text: t }), h("dd", { text: d })])))),
    h("div", { class: "stack" },
      h("details", { class: "fold panel-fold", "data-k": "help-cli" }, h("summary", null, icon("chevron", "sm turn"), "The same things from a terminal"), h("div", { class: "table-wrap fold-body" }, h("table", { class: "data" },
        h("thead", null, h("tr", null, h("th", { text: "To" }), h("th", { text: "Run" }))),
        h("tbody", null, [
          ["Open this dashboard", "rt ui"], ["See what needs you", "rt status"], ["Add an AI", "rt seat add opus --model claude-opus-5-5 --app claude-code"],
          ["Start an AI", "rt launch opus"], ["Connect an app you open yourself", "rt setup codex"], ["Give a goal", "rt goal \"what to build\" --review mid"],
          ["Read and approve the plan", "rt plan view, then rt plan lock"], ["List tasks", "rt task list"], ["Accept found work", "rt task accept T7"],
          ["Check changes when asked", "rt review get T3, then rt review submit T3 approve"], ["Report a problem", "rt alert raise 3 \"what is wrong\""],
          ["Stop every AI", "rt freeze"], ["Usage and limits", "rt usage"], ["Add a note", "rt memory add \"note\""],
          ["Check the setup", "rt doctor"], ["Notifications", "rt watch"],
        ].map(([a, b]) => h("tr", null, h("td", { text: a }), h("td", { class: "mono small", text: b }))))))),
      panel("Where things are", null, h("dl", { class: "kv" },
        h("dt", { text: "Project" }), h("dd", { class: "mono", text: st.project.root }),
        h("dt", { text: "Roundtable's data" }), h("dd", { class: "mono", text: st.project.home }),
        h("dt", { text: "AIs' copies" }), h("dd", { class: "mono pre", text: st.seats.filter(x => x.worktree).map(x => x.worktree).join("\n") || "none yet" }))),
      panel("Credits", null, h("p", { class: "prose small", text: "Planning together borrows from Andrej Karpathy's LLM Council (anonymous peer review and a chairman). Task tracking learns from Steve Yegge's Beads and Gas Town, and messaging from MCP Agent Mail." })))));

/* ---------------------------------------------------------------- boot */

applyTheme();
route = parseRoute();
window.addEventListener("hashchange", () => { route = parseRoute(); if (taskRoute()) loadTask(taskRoute()).then(render); render(); });
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  const open = APP.querySelector("details.menu[open]");
  if (open) { open.open = false; const sm = open.querySelector("summary"); if (sm) sm.focus(); }
});
document.addEventListener("click", e => { APP.querySelectorAll("details.menu[open]").forEach(d => { if (!d.contains(e.target)) d.open = false; }); });
refresh(true);
setInterval(() => { if (document.visibilityState === "visible") refresh(false); }, 3000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(false); });
