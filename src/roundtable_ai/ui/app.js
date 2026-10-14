/* Roundtable dashboard: the room.
   No framework, no build step: plain DOM rebuilt from polled state.
   Everything shown comes from /api/state; every change goes through /api/action
   (a Roundtable operation, as the human) or /api/do (set up, start, connect).

   One screen. The conversation is in the middle: everything the AIs do arrives as a message,
   and whatever needs you is pinned above the message box. The team sits around the table
   on the left, the plan is on the right. Everything else opens as a panel over the room
   and closes with Esc. */
"use strict";

const TOKEN = document.querySelector('meta[name="rt-token"]').content;
const APP = document.getElementById("app");
const TOASTS = document.getElementById("toasts");

let S = null;            // last state from the server
let lastJSON = "";
let route = { page: "room", parts: [], sub: "" };
const cache = { task: {}, diff: {}, doctor: null, log: null, logKey: "", older: [], olderDone: false, activity: {}, council: {}, models: {} };
const ui = {
  mode: "note", level: null, allAsks: false, started: {}, preview: {}, confirm: {}, pick: {}, wstep: 0,
  accepting: {}, editOpen: false, linkOpen: false, cancelPlan: false, showDone: false, adding: false,
  compose: "goal", askSkip: {}, followUp: null, modelOpen: null, freeOnly: false,
};
const PAGES = {};

/* ---------------------------------------------------------------- small helpers */

function store(key, value) {
  try { if (value === undefined) return JSON.parse(localStorage.getItem(key) || "null"); localStorage.setItem(key, JSON.stringify(value)); }
  catch (e) { return null; }
  return value;
}

function h(tag, props, ...kids) {
  const el = props && props.svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
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
function capital(t) { t = String(t || ""); return t.charAt(0).toUpperCase() + t.slice(1); }
function fit(t, n) { t = String(t || ""); return t.length > n ? t.slice(0, n - 1) + "…" : t; }
function csv(v) { const out = String(v || "").split(",").map(x => x.trim()).filter(Boolean); return out.length ? out : null; }
function cmds(v) { return String(v || "").split("&&").map(x => x.trim()).filter(Boolean); }
function monogram(name) { const c = String(name || "").replace(/[^a-z0-9]/gi, ""); return (c.charAt(0).toUpperCase() + (c.charAt(1) || "")).slice(0, 2); }
function listWords(xs) { return xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1]; }
function who(name) { return name === "human" ? "you" : name === "system" ? "Roundtable" : name; }

/* "claude-opus-5-5" -> "Claude Opus 5.5", "gpt-6.1-sol" -> "GPT-6.1 Sol" */
function prettyModel(m) {
  if (!m) return "";
  const parts = String(m).split(/[-_ ]+/).filter(Boolean);
  const out = [];
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i];
    if (/^\d/.test(p)) {
      let n = p;
      while (/^\d+$/.test(p) && i + 1 < parts.length && /^\d+$/.test(parts[i + 1])) n += "." + parts[++i];
      if (out.length && out[out.length - 1] === "GPT") out[out.length - 1] = "GPT-" + n; else out.push(n);
    } else out.push(/^gpt$/i.test(p) ? "GPT" : p.charAt(0).toUpperCase() + p.slice(1));
  }
  return out.join(" ");
}

const PRIORITY = ["Urgent", "High", "Normal", "Low", "Someday"];
const CHECKING = { low: "Light", mid: "Standard", high: "Thorough" };
const CHECKING_TEXT = {
  low: "Tests must pass. No AI reads another's code. Fastest and cheapest.",
  mid: "An AI from another company skims every change, and reads 1 task in 5 (and every risky one) in full.",
  high: "Two AIs read every line and leave comments that must be answered. Slowest; several times the tokens.",
};
const LEVELS = [[1, "Note", "For the record; nobody has to act."], [2, "Heads-up", "Worth knowing for anyone working nearby."],
  [3, "Problem", "The AIs it affects must acknowledge it before taking new work."], [4, "Blocking", "Holds the affected files until it is fixed."],
  [5, "Critical", "Freezes the files and tells every AI to stop."]];
const ACTIVE = ["claimed", "changes_requested", "proving", "in_review", "merge_blocked"];
const isLivePlan = p => p && !["done", "cancelled"].includes(p.stage);
const STAGE_STEPS = [["drafting", "Each AI writes a plan"], ["critique", "They comment on each other's"], ["merging", "One AI combines them"],
  ["proposed", "They agree on it"], ["awaiting_human", "You approve it"], ["locked", "They build it"]];

const APP_GROUPS = [
  ["terminal", "Opens in a terminal", "terminal", "Roundtable opens a terminal window for it, already connected."],
  ["editor", "Opens in a code editor", "code", "Roundtable opens its folder in the editor; you send one message."],
  ["desktop", "Desktop apps", "desktop", "You open the app yourself and send one message."],
  ["manual", "Anything else", "settings", "Any app that supports MCP. You add Roundtable to its settings."],
];
const APP_NAMES = {
  "claude-code": ["Claude Code", "Anthropic, in a terminal"], "claude-vscode": ["Claude Code", "Anthropic, in VS Code"], "claude-app": ["Claude app", "Plans and checks; can't edit files"],
  "codex-cli": ["Codex", "OpenAI, in a terminal"], "codex-vscode": ["Codex", "OpenAI, in VS Code"], "codex-app": ["ChatGPT app", "OpenAI, Codex mode"],
  "gemini-cli": ["Gemini CLI", "Google"], "qwen-code": ["Qwen Code", "Alibaba"], "opencode": ["opencode", "75+ models, some free"],
  "copilot-cli": ["Copilot CLI", "GitHub"], "cursor": ["Cursor", "Any model"], "other": ["Another app", "With MCP support"],
};
const SUGGESTED = ["claude-code", "codex-cli"];
const RUNS_ITSELF = ["claude-code", "codex-cli", "opencode"];
const groupOf = a => a.start === "vscode" || a.start === "editor" ? "editor" : a.start;

function seatOf(handle) { return S && S.seats ? S.seats.find(x => x.handle === handle) : null; }
function taskOf(id) { return S && S.tasks ? S.tasks.find(t => t.id === id) : null; }
function progress(st) {
  const real = st.tasks.filter(t => t.kind !== "epic" && !["cancelled", "backlog"].includes(t.status));
  return { done: real.filter(t => t.status === "done").length, total: real.length, active: real.filter(t => ACTIVE.includes(t.status)).length };
}

/* Texts from the server are written for models; say them the way a person would. */
function plainText(t) {
  return String(t || "")
    .replace(/\bby the human\b/g, "by you").replace(/\bthe human\b/g, "you")
    .replace(/\s*\(PR\d+\)/g, "")
    .replace(/review depth:? (low|mid|high)/g, (m, l) => ({ low: "light", mid: "standard", high: "thorough" }[l]) + " checking")
    .replace(/no review, the passed (proof|tests) is the gate/, "no AI reads the code; passing tests is enough")
    .replace(/\bproofs?\b/g, "tests").replace(/\bProofs?\b/g, "Tests")
    .replace(/\blocked\b/g, "approved").replace(/\block\b/g, "approve").replace(/\bbacklog\b/g, "waiting list")
    .replace(/\bseats?\b/g, m => m === "seat" ? "AI" : "AIs");
}

/* Task ids in a sentence become small links that open the task. */
function linkify(text) {
  const out = [];
  String(text || "").split(/\b(T\d+)\b/).forEach((part, i) => {
    if (i % 2) out.push(h("a", { class: "tid", href: "#/task/" + part, text: part }));
    else if (part) out.push(part);
  });
  return out;
}

/* Markdown the AIs write (answers, diagnoses), turned into DOM nodes: never HTML from the text itself. */
const MD_BLOCK = /^(```|#{1,4}\s|>\s?|\s*(?:[-*+]|\d+[.)])\s+|\s*\|.*\|\s*$)/;
function md(text) {
  const root = h("div", { class: "md" });
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      root.append(h("pre", null, h("code", { text: buf.join("\n") })));
      continue;
    }
    const hm = line.match(/^(#{1,4})\s+(.*)$/);
    if (hm) { root.append(h("h" + Math.min(6, hm[1].length + 2), null, inline(hm[2]))); i++; continue; }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = r => r.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const body = rows.filter(r => !/^\s*\|?\s*:?-{2,}/.test(r));
      root.append(h("div", { class: "md-table" }, h("table", null, body.map((r, k) => h("tr", null, cells(r).map(c => h(k ? "td" : "th", null, inline(c))))))));
      continue;
    }
    if (/^\s*(?:[-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const list = h(ordered ? "ol" : "ul");
      while (i < lines.length && /^\s*(?:[-*+]|\d+[.)])\s+/.test(lines[i])) {
        let item = lines[i].replace(/^\s*(?:[-*+]|\d+[.)])\s+/, "");
        i++;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*(?:[-*+]|\d+[.)])\s+/.test(lines[i])) item += " " + lines[i++].trim();
        list.append(h("li", null, inline(item)));
      }
      root.append(list);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      root.append(h("blockquote", null, inline(buf.join(" "))));
      continue;
    }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { root.append(h("hr")); i++; continue; }
    if (!line.trim()) { i++; continue; }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !MD_BLOCK.test(lines[i])) buf.push(lines[i++]);
    if (!buf.length) buf.push(lines[i++]);
    root.append(h("p", null, inline(buf.join("\n"))));
  }
  return root;
}

function inline(text) {
  const out = [];
  const re = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\s][^*\n]*\*)|(\[[^\]\n]+\]\((https?:\/\/[^)\s]+)\))|\b(T\d+)\b/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) out.push(h("code", { text: m[1].slice(1, -1) }));
    else if (m[2]) out.push(h("strong", { text: m[2].slice(2, -2) }));
    else if (m[3]) out.push(h("em", { text: m[3].slice(1, -1) }));
    else if (m[4]) out.push(h("a", { href: m[5], target: "_blank", rel: "noopener noreferrer", text: m[4].slice(1, m[4].indexOf("]")) }));
    else if (m[6]) out.push(h("a", { class: "tid", href: "#/task/" + m[6], text: m[6] }));
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out.flatMap(x => typeof x === "string" ? x.split("\n").flatMap((s, k) => k ? [h("br"), s] : [s]) : [x]);
}

/* Long markdown folds like longText: a few lines and "Read more". */
function longMd(text, key, limit) {
  text = String(text || "");
  const long = text.length > (limit || 700) || text.split("\n").length > 12;
  const open = expanded.has(key);
  const body = md(text);
  if (!long) return body;
  if (!open) body.classList.add("md-clamp");
  return h("div", { class: "folded" }, body, h("button", { class: "more-link", type: "button", "aria-expanded": String(open),
    onclick: () => { if (open) expanded.delete(key); else expanded.add(key); render(); } }, open ? "Show less" : "Read all of it"));
}

/* ---------------------------------------------------------------- routes */

const ALIAS = { overview: "room", home: "room", inbox: "room", tasks: "room", work: "room", models: "team", memory: "notes",
  activity: "history", guide: "help", more: "team", reviews: "review", ask: "council", questions: "council" };
const DRAWERS = ["plan", "task", "review", "ai", "add", "team", "alerts", "found", "settings", "usage", "notes", "help", "history", "switch", "council"];

function parseRoute() {
  const parts = (location.hash || "#/room").replace(/^#\/?/, "").split("/").filter(Boolean).map(x => decodeURIComponent(x));
  let page = parts[0] || "room";
  let rest = parts.slice(1);
  if ((page === "work" || page === "tasks") && rest[0] && /^T\d/i.test(rest[0])) page = "task";         // old links: #/work/T3
  else if (page === "inbox" && rest[0] === "review" && rest[1]) { page = "review"; rest = [rest[1]]; }   // #/inbox/review/T3
  else if (page === "team" && rest[0] === "add") { page = "add"; rest = rest.slice(1); }                 // #/team/add
  else if (page === "team" && rest[0]) page = "ai";                                                    // #/team/opus
  page = ALIAS[page] || page;
  if (!PAGES[page]) page = "room";
  return { page, parts: rest, sub: rest[0] || "" };
}
function go(hash) { if (location.hash === hash) render(); else location.hash = hash; }
function close() { go("#/room"); }

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
  try {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ token: TOKEN }, body)) });
    return await r.json();
  } catch (e) { return { ok: false, message: "The dashboard did not answer", hint: "Is `rt ui` still running? Start it again, then reload this page." }; }
}

function busy(btn, on) {
  if (!btn) return;
  btn.disabled = on;
  btn.classList.toggle("busy", on);
}

function showResult(res, okTitle, okBody) {
  if (res.ok) {
    const first = plainText((res.text || "").split("\n")[0]);
    toast(okTitle || "Done", okBody !== undefined ? okBody : okTitle ? first : plainText((res.text || "").split("\n").slice(1).join("\n")));
    return true;
  }
  const cmd = res.command || (res.data && res.data.command);
  toast(capital(plainText(res.message)) || "That did not work", plainText(res.hint || ""), { error: true, copy: cmd || null });
  return false;
}

async function act(op, params, opts) {
  opts = opts || {};
  busy(opts.button, true);
  const res = await post("/api/action", { op, params: params || {} });
  busy(opts.button, false);
  const ok = opts.quiet && res.ok ? true : showResult(res, opts.title || capital(plainText((res.text || "Done").split("\n")[0])), opts.body);
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

function taskRoute() { return route.page === "task" && /^T\d/i.test(route.sub) ? route.sub.toUpperCase() : ""; }

async function refresh(force) {
  let next;
  try { next = await getJSON("/api/state"); }
  catch (e) { if (S) toast("Lost contact with the dashboard", "Start it again with: rt ui", { error: true }); return; }
  if (taskRoute()) await loadTask(taskRoute());
  if (route.page === "ai" && route.sub) await loadActivity(route.sub);
  if (route.page === "council" && route.sub) await loadCouncil(route.sub, next);
  const json = JSON.stringify(next) + JSON.stringify(cache.task[taskRoute()] || null) + (route.page === "ai" ? JSON.stringify(cache.activity[route.sub] || null) : "")
    + (route.page === "council" ? JSON.stringify(cache.council[route.sub] || null) : "");
  if (!force && json === lastJSON) return;
  lastJSON = json;
  S = next;
  render();
}

async function loadCouncil(id, st) {
  const known = cache.council[id];
  const live = ((st || S || {}).councils || []).find(c => c.id === id);
  if (known && known.stage && ["done", "failed", "cancelled"].includes(known.stage) && (!live || live.stage === known.stage)) return;
  try { cache.council[id] = await getJSON("/api/council?id=" + encodeURIComponent(id)); } catch (e) { /* shown as loading */ }
}

async function loadActivity(handle) {
  try { cache.activity[handle] = await getJSON("/api/activity?n=80&seat=" + encodeURIComponent(handle)); } catch (e) { /* shown as loading */ }
}

async function loadTask(id) {
  try { cache.task[id] = await getJSON("/api/task?id=" + encodeURIComponent(id)); } catch (e) { /* shown as missing */ }
}

/* ---------------------------------------------------------------- render, keeping what the person typed */

const SCROLLERS = [".feed", ".drawer-body", ".plan-side", ".crew", ".waiting", ".welcome-main"];

function snapshot() {
  const out = { fields: {}, focus: null, open: {}, scroll: {}, win: window.scrollY };
  APP.querySelectorAll("[data-k]").forEach(el => {
    if (el.tagName === "DETAILS") { out.open[el.dataset.k] = el.open; return; }
    out.fields[el.dataset.k] = el.type === "checkbox" || el.type === "radio" ? { checked: el.checked } : { value: el.value, def: el.dataset.def };
  });
  SCROLLERS.forEach(sel => {
    const el = APP.querySelector(sel);
    if (el) out.scroll[sel] = { top: el.scrollTop, bottom: el.scrollHeight - el.scrollTop - el.clientHeight < 48 };
  });
  const a = document.activeElement;
  if (a && a.dataset && a.dataset.k) out.focus = { k: a.dataset.k, start: a.selectionStart, end: a.selectionEnd };
  else if (a && a.dataset && a.dataset.f) out.focus = { f: a.dataset.f };
  return out;
}

function restore(snap, samePage) {
  APP.querySelectorAll("[data-k]").forEach(el => {
    if (el.tagName === "DETAILS") { if (el.dataset.k in snap.open) el.open = snap.open[el.dataset.k]; return; }
    const f = snap.fields[el.dataset.k];
    if (!f) return;
    if ("checked" in f) el.checked = f.checked;
    else if (!(f.def !== undefined && f.value === f.def && el.dataset.def !== undefined)) el.value = f.value;   // untouched: take the new default
    if (el.tagName === "TEXTAREA" && el.classList.contains("grow")) autosize(el);
  });
  // the conversation keeps its place whatever opens over it, and follows new messages when you are at the bottom
  const feed = APP.querySelector(".feed");
  if (feed) {
    const was = snap.scroll[".feed"];
    feed.scrollTop = !was || was.bottom ? feed.scrollHeight : was.top;
  }
  if (samePage) {
    SCROLLERS.slice(1).forEach(sel => { const el = APP.querySelector(sel); if (el && snap.scroll[sel]) el.scrollTop = snap.scroll[sel].top; });
    window.scrollTo(0, snap.win);
  }
  if (snap.focus) {
    const el = snap.focus.k ? APP.querySelector(`[data-k="${CSS.escape(snap.focus.k)}"]`) : APP.querySelector(`[data-f="${CSS.escape(snap.focus.f)}"]`);
    if (el) { el.focus({ preventScroll: true }); try { if (snap.focus.start != null) el.setSelectionRange(snap.focus.start, snap.focus.end); } catch (e) { /* not a text field */ } }
  }
}

let renderedKey = "";
let drawerShown = "";
function render() {
  if (!S) return;
  const view = S.mode === "setup" ? "setup" : inWelcome() ? "welcome" : "room";
  const key = S.mode + ":" + view + ":" + route.page + ":" + route.parts.join("/") + ":" + ui.wstep;
  const snap = snapshot();
  const same = key === renderedKey;
  renderedKey = key;
  const drawerKey = view === "room" && DRAWERS.includes(route.page) ? route.page + "/" + route.parts.join("/") : "";
  const freshDrawer = drawerKey && drawerKey !== drawerShown;
  drawerShown = drawerKey;
  APP.replaceChildren(view === "setup" ? setupScreen(S) : view === "welcome" ? welcomeScreen(S) : roomView(freshDrawer));
  const title = S.mode === "project" && S.project ? S.project.name + " · Roundtable" : "Roundtable";
  if (document.title !== title) document.title = title;
  restore(snap, same);
  if (!same) {
    const target = APP.querySelector(".drawer h1") || (view !== "room" ? APP.querySelector("h1, h2") : null);
    if (target && (freshDrawer || view !== "room")) { target.setAttribute("tabindex", "-1"); target.focus({ preventScroll: true }); }
    if (view !== "room") window.scrollTo(0, 0);
  }
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
function themeButton(withLabel) {
  const theme = store("rt.theme") || "auto";
  return h("button", { class: "ghost" + (withLabel ? "" : " icon-only"), type: "button", title: "Theme: " + theme, "aria-label": "Change the theme (now " + theme + ")", onclick: cycleTheme },
    icon(theme === "dark" ? "moon" : "sun", "sm"), withLabel ? h("span", { text: "Theme: " + capital(theme) }) : null);
}

/* ---------------------------------------------------------------- what each AI is doing, in a few words */

function running(x) { return !!(x.runner && x.runner.running); }
function lampOf(x) {
  if (x.status === "paused" || !(x.active || x.live)) return "";
  if (running(x)) return x.runner.state === "working" ? "busy" : "on";
  return x.tasks.length || busyPlanning(x) ? "busy" : "on";
}

function busyPlanning(x) {
  const p = S.plan;
  if (!isLivePlan(p)) return "";
  const me = p.people.find(q => q.seat === x.handle);
  if (!me) return "";
  if (p.stage === "drafting" && me.planner && !me.drafted) return "Writing its plan";
  if (p.stage === "critique" && me.critiques_done < me.critiques) return "Commenting on the plans";
  if (p.stage === "merging" && me.chair) return "Combining the plans";
  if (["proposed", "voting"].includes(p.stage) && !me.approval) return "Reading the combined plan";
  return "";
}

function seatPhrase(x) {
  if (x.status === "paused") return "Paused";
  if (running(x)) {
    if (x.runner.state === "stuck") return "Stuck: retrying soon";
    if (x.runner.state === "paused") return "Paused with everyone";
    if (x.runner.state !== "working") return "Waiting for work";
  }
  if (!x.joined_ever && !running(x)) return x.status === "active" ? "Not started yet" : capital(x.status);
  if (x.tasks.length) {
    const t = taskOf(x.tasks[0]);
    const verb = t && t.status === "changes_requested" ? "Fixing" : t && ["proving", "in_review"].includes(t.status) ? "Waiting on checks for" : "Building";
    return `${verb} ${x.tasks[0]}` + (x.tasks.length > 1 ? ` +${x.tasks.length - 1}` : "");
  }
  const reviewing = S.tasks.find(t => t.status === "in_review" && (t.reviewers || []).includes(x.handle));
  if (reviewing) return "Checking " + reviewing.id;
  const planning = busyPlanning(x);
  if (planning) return (x.active || x.live) ? planning : "Not running · " + ({ "Writing its plan": "its plan is due", "Commenting on the plans": "its comments are due",
    "Combining the plans": "the combined plan is due", "Reading the combined plan": "its answer is due" }[planning] || "work waits");
  if (running(x)) return "Working";
  if (x.active || x.live) return x.doing ? capital(plainText(x.doing)) : "Ready for work";
  return "Not running · seen " + (/^\d+s\b/.test(x.seen) ? "just now" : x.seen);
}

function needsStart(x) { return x.status === "active" && !x.joined_ever && !running(x); }
function idleSeat(x) { return x.status === "active" && !running(x) && !(x.active || x.live); }

function avatar(handle, size, noLamp) {
  const x = seatOf(handle);
  const c = handle === "human" ? "you" : x ? x.company : "other";
  const label = handle === "human" ? "You" : handle === "system" ? "RT" : monogram(handle);
  const el = h("span", { class: "av" + (size ? " " + size : ""), "data-c": c, "aria-hidden": "true" }, label);
  if (x && !noLamp && size !== "sm") el.append(h("span", { class: "lamp" + (lampOf(x) ? " " + lampOf(x) : "") }));
  return el;
}

function displayName(handle) { return handle === "human" ? "You" : handle === "system" ? "Roundtable" : handle; }

/* ---------------------------------------------------------------- the room */

function roomView(freshDrawer) {
  const wrap = h("div", { class: "room-wrap" }, h("div", { class: "room" }, crew(), talk(), planSide()));
  if (DRAWERS.includes(route.page)) wrap.append(...drawer(route.page, freshDrawer));
  return wrap;
}

function crew() {
  const p = S.project;
  return h("aside", { class: "crew", "aria-label": "Your team" },
    h("div", { class: "crew-head" }, h("img", { src: "/icon.svg", alt: "Roundtable" }),
      h("button", { class: "proj", type: "button", title: p.root, onclick: () => go("#/switch") },
        h("strong", { text: p.name }), h("small", { text: "Switch project" }))),
    h("div", { class: "table-art" }, tableArt(S.seats, false)),
    h("h2", { text: S.seats.length ? "At the table" : "Nobody at the table yet" }),
    h("ul", { class: "mates" }, S.seats.map(x => {
      const phrase = seatPhrase(x);
      return h("li", null, h("button", { class: "mate", type: "button", "aria-current": route.page === "ai" && route.sub === x.handle ? "true" : null,
        "aria-label": `${x.handle}, ${prettyModel(x.model)}: ${phrase}`, onclick: () => go("#/ai/" + x.handle) },
        avatar(x.handle), h("span", { class: "who" }, h("strong", { text: x.handle }), h("span", { class: needsStart(x) || (x.runner && x.runner.state === "stuck") || /^Not running · its|^Not running · the|due$/.test(phrase) ? "you" : null, text: phrase }))));
    })),
    h("button", { class: "add-mate", type: "button", "aria-label": "Add an AI", onclick: () => go("#/add") }, icon("plus", "sm"), h("span", { text: "Add an AI" })),
    h("div", { class: "crew-foot" }, pauseButton(),
      h("div", { class: "tools" },
        h("button", { class: "ghost", type: "button", onclick: () => go("#/settings") }, icon("settings", "sm"), h("span", { text: "Settings" })),
        h("button", { class: "ghost", type: "button", onclick: () => go("#/help") }, icon("help", "sm"), h("span", { text: "Help" })),
        themeButton(false))));
}

function pauseButton(full) {
  if (!S.seats.length) return null;
  if (S.project.frozen) return h("button", { class: "go", type: "button", onclick: e => act("admin.unfreeze", {}, { button: e.currentTarget, title: "Your AIs can work again" }) },
    icon("play", "sm"), h("span", { text: "Let them work again" }));
  const sure = ui.confirm.pause;
  return h("button", { class: sure ? "danger" : "ghost" + (full ? "" : ""), type: "button", "data-f": "pause", title: "Every AI stops at its next step until you let them work again",
    onclick: e => {
      if (!ui.confirm.pause) { ui.confirm.pause = true; render(); setTimeout(() => { ui.confirm.pause = false; render(); }, 4000); return; }
      ui.confirm.pause = false;
      act("admin.freeze", { reason: "paused from the dashboard" }, { button: e.currentTarget, title: "Every AI is paused" });
    } }, icon("pause", "sm"), h("span", { text: sure ? "Click again to pause them all" : "Pause everyone" }));
}

/* The table drawn from above: one chair per AI in its maker's colour, lit while its app is open. */
function tableArt(seats, big) {
  const W = 260, H = big ? 210 : 158, cx = W / 2, cy = H / 2, rx = big ? 82 : 74, ry = big ? 52 : 38;
  const list = seats.filter(x => x.status !== "removed");
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": list.length ? "The table: " + list.map(x => `${x.handle} ${seatPhrase(x).toLowerCase()}`).join("; ") : "An empty table" });
  svg.append(s("ellipse", { class: "cloth", cx, cy, rx, ry }), s("ellipse", { class: "weave", cx, cy, rx: rx - 9, ry: ry - 8 }));
  if (!big) {
    const [l1, l2] = tableWords();
    svg.append(s("text", { class: "center", x: cx, y: cy + (l2 ? -1 : 5), "text-anchor": "middle" }, l1));
    if (l2) svg.append(s("text", { class: "center2", x: cx, y: cy + 17, "text-anchor": "middle" }, l2));
  }
  const n = list.length || 4;
  for (let i = 0; i < n; i++) {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n + (n === 2 ? Math.PI / 2 : 0);
    const x = cx + (rx + 22) * Math.cos(a), y = cy + (ry + 21) * Math.sin(a);
    const seat = list[i];
    if (!seat) { svg.append(s("circle", { class: "chair chair-idle", cx: x, cy: y, r: 13 })); continue; }
    const lamp = lampOf(seat);
    if (lamp) svg.append(s("circle", { class: "glow " + lamp, cx: x, cy: y, r: 18 }));
    const joined = seat.joined_ever;
    svg.append(s("circle", { class: "chair" + (joined ? "" : " chair-idle"), "data-c": seat.company, cx: x, cy: y, r: 13 }),
      s("text", { class: joined ? "mono" : "mono-dim", x, y: y + 4.5, "text-anchor": "middle" }, monogram(seat.handle)));
  }
  return svg;
}

function tableWords() {
  const p = S.plan;
  if (S.project.frozen) return ["Paused", ""];
  if (!S.seats.length) return ["An empty table", ""];
  if (!isLivePlan(p)) return [p && p.stage === "done" ? "Plan finished" : "Waiting for a goal", plural(S.seats.length, "AI")];
  if (p.stage === "locked") { const pr = progress(S); return [`${pr.done} of ${pr.total} done`, "building"]; }
  if (p.stage === "awaiting_human") return ["Waiting for you", "plan ready"];
  return ["Planning", plural(S.seats.length, "AI")];
}

function headline() {
  const p = S.plan;
  if (S.project.frozen) return ["Everyone is paused", plainText(S.project.frozen_reason) || "No AI takes another step until you let them work again."];
  if (!S.seats.length) return ["Nobody at the table yet", "Add the AIs that will work together."];
  if (!isLivePlan(p)) return [p && p.stage === "done" ? "Finished. Ready for the next goal" : "Waiting for a goal", "Write it in the box at the bottom."];
  if (p.stage === "locked") { const pr = progress(S); return [`Building: ${pr.done} of ${plural(pr.total, "task")} done`, "Goal: " + p.goal]; }
  if (p.stage === "awaiting_human") return ["The plan is ready for you", "Goal: " + p.goal];
  return [p.stage_label, "Goal: " + p.goal];
}

function talk() {
  const [title, sub] = headline();
  return h("main", { class: "talk", "aria-label": "The conversation" },
    h("header", { class: "talk-head" },
      h("div", { class: "status" }, h("strong", { text: title }), sub ? h("span", { text: sub, title: sub }) : null),
      h("button", { class: "ghost show-plan-btn", type: "button", onclick: () => go("#/plan") }, icon("plan", "sm"), h("span", { text: "Plan" })),
      h("button", { class: "ghost icon-only", type: "button", title: "Search everything that happened", "aria-label": "Search everything that happened", onclick: () => go("#/history") }, icon("search")),
      h("button", { class: "ghost icon-only only-narrow", type: "button", title: "Team and more", "aria-label": "Team and more", onclick: () => go("#/team") }, icon("team"))),
    feedView(), asksView(), composer());
}

/* ---------------------------------------------------------------- the conversation */

const HIDDEN = new Set(["task.ready", "lease.released", "lease.acquired", "seat.seen", "review.assigned"]);
const QUIET = new Set(["vote.cast", "memory.pinned", "memory.forgotten", "task.linked", "task.edited", "human.config", "task.review_level", "task.reassigned", "task.proving", "review.skipped"]);

function rest(text, re) { const m = String(text || "").match(re); return m ? m[1] : null; }

/* One event as one sentence. Returns null for bookkeeping nobody needs to read. */
function say(e) {
  const t = e.text || "";
  const T = e.task;
  const title = T && taskOf(T) ? taskOf(T).title : "";
  switch (e.type) {
    case "project.created": return { marker: "Roundtable is set up. Your AIs will meet here.", icon: "check" };
    case "seat.added": {
      const m = t.match(/seat (\S+) added \(([^,]+),/);
      return m ? { actor: "human", text: `Added ${m[1]} (${prettyModel(m[2])}) to the table` } : { actor: "human", text: plainText(t) };
    }
    case "seat.joined": return { text: "Joined the table", tone: "quiet" };
    case "seat.removed": return { actor: "human", text: plainText(t) };
    case "seat.paused": case "seat.resumed": case "seat.released": return { text: plainText(t), tone: "quiet" };
    case "plan.goal": {
      const pid = rest(t, /^P(\d+) goal/);
      const goal = (pid && S.goals && S.goals[pid]) || (rest(t, /goal: (.*?)( · |$)/) || t);
      const quick = / · quick: /.test(t);
      return { actor: "human", text: (quick ? "New goal (just do it): " : "New goal: ") + goal };
    }
    case "plan.draft": return { text: "Wrote its plan. The others can't see it until every plan is in." };
    case "plan.critique":
      if (/drafting closed/.test(t)) return { marker: "Every plan is in. Now each AI comments on the others' plans, without knowing who wrote which.", icon: "review" };
      return { text: "Commented on plan " + (rest(t, /draft (\w+)/) || ""), tone: "quiet" };
    case "plan.merging": return { marker: `All comments are in. ${rest(t, /chair (\S+)/) || "One AI"} is combining the plans into one.`, icon: "plan" };
    case "plan.proposed": return { text: `Proposed the combined plan${rest(t, /\((\d+ tasks?)\)/) ? " (" + rest(t, /\((\d+ tasks?)\)/) + ")" : ""}. The others read it now.` };
    case "plan.approved": return { text: "Agreed to the plan", tone: "good" };
    case "plan.objected": return { text: "Objected to the plan: " + plainText(rest(t, /: (.*)$/) || t), tone: "bad" };
    case "plan.awaiting_human": return { marker: "Every AI agreed. The plan is waiting for you.", icon: "plan", you: true };
    case "plan.locked": return { marker: `You approved the plan${rest(t, /: (\d+ tasks?)/) ? ": " + rest(t, /: (\d+ tasks?)/) : ""}. The AIs start building.`, icon: "check" };
    case "plan.cancelled": return { marker: "The plan was cancelled. " + plainText(rest(t, /: (.*)$/) || ""), icon: "x" };
    case "plan.done": return { marker: "Every task in the plan is done.", icon: "check" };
    case "plan.amend_proposed": return { text: "Wants to change the approved plan: " + plainText(rest(t, /: (.*)$/) || t) };
    case "task.created": return { marker: plainText(t.replace(/ from plan P\d+/, "")).replace(/^(\d+) tasks created/, "$1 tasks added to the work").replace(/: T.*$/, ""), icon: "plan" };
    case "task.claimed": return { text: `Started ${T}${title ? ": " + title : ""}` };
    case "task.checkpoint": return { text: `${T}: ${plainText((rest(t, /checkpoint: (.*?)( \[|$)/) || t))}`, tone: "quiet" };
    case "task.filed": return { text: `Found more work: ${T} ${title || rest(t, /\]: (.*?)( \(found|$)/) || ""}. It waits for your OK.` };
    case "task.accepted": return { text: `${T} was added to the work`, tone: "quiet" };
    case "task.proof_passed": return { text: `${T} passed its tests`, tone: "good" };
    case "task.proof_failed": return { text: `${T} failed its tests`, tone: "bad" };
    case "task.changes_requested": return { text: `${T} needs changes: ` + plainText(rest(t, /: (.*)$/) || "see the review"), tone: "bad" };
    case "task.done": return { text: `${T} is done and merged into your project`, tone: "good" };
    case "task.merge_blocked": return { text: `${T} is approved but can't be merged yet`, tone: "bad" };
    case "task.cancelled": return { text: `${T} was cancelled`, tone: "quiet" };
    case "review.submitted": return /approve/.test(t) ? { text: `Approved the changes in ${T}`, tone: "good" } : { text: `Asked for changes in ${T}`, tone: "bad" };
    case "review.reply": return { text: `Answered the review of ${T}`, tone: "quiet" };
    case "review.level_requested": return { text: plainText(t), tone: "quiet" };
    case "alert.raised": {
      const m = t.match(/^A\d+ L(\d) \w+: (.*)$/);
      return m ? { text: `Reported a ${(LEVELS[Number(m[1]) - 1] || LEVELS[2])[1].toLowerCase()}: ${m[2]}`, tone: Number(m[1]) >= 3 ? "bad" : "" } : { text: plainText(t), tone: "bad" };
    }
    case "alert.resolved": return { text: "Solved a problem: " + plainText(rest(t, /: (.*)$/) || t), tone: "good" };
    case "alert.acked": return { text: "Acknowledged a problem", tone: "quiet" };
    case "memory.added": return e.actor === "human" ? { text: rest(t, /remembered N\d+: (.*)$/) || t, said: true } : { text: rest(t, /remembered N\d+: (.*)$/) || t };
    case "seat.changed": {
      const m = t.match(/^seat (\S+): (.*)$/);
      if (!m) return { actor: "human", text: plainText(t), tone: "quiet" };
      const parts = m[2].split(", ").map(x => x.startsWith("model ") ? "uses " + prettyModel(x.slice(6))
        : x === "effort app default" ? "thinks as hard as its app decides" : x.startsWith("effort ") ? "thinks at " + (EFFORT_LABEL[x.slice(7)] || x.slice(7)) + " effort" : x);
      return { actor: "human", text: `${m[1]} now ${listWords(parts)}`, tone: "quiet" };
    }
    case "vote.opened": return { text: "Asked everyone to vote: " + (rest(t, /^V\d+: (.*?)( \(|$)/) || t) };
    case "vote.tied": return { marker: "The vote is tied. You decide.", icon: "alert", you: true };
    case "vote.decided": return { text: plainText(t) };
    case "human.freeze": return { marker: "You paused every AI.", icon: "pause" };
    case "human.unfreeze": return { marker: "You let the AIs work again.", icon: "play" };
    case "human.compact": return null;
    case "council.asked": return { council: rest(t, /^(Q\d+)/), actor: "human", text: "Asked the table: " + (rest(t, /^Q\d+: (.*?) · asked/) || t) };
    case "council.rescue": return { council: rest(t, /\((Q\d+)\)\s*$/), actor: "system", text: plainText(t) };
    case "council.ranking": case "council.combining": case "council.done": case "council.failed": case "council.cancelled": return null;
    case "suggestion.sent": return { text: plainText(t), tone: "quiet" };
    case "suggestion.replied": return { text: plainText(t), tone: "quiet" };
    default: {
      if (HIDDEN.has(e.type)) return null;
      let text = t;
      if (text.startsWith(e.actor + " ")) text = text.slice(e.actor.length + 1);
      return { text: capital(plainText(text)), tone: QUIET.has(e.type) ? "quiet" : e.level >= 4 ? "bad" : "" };
    }
  }
}

/* Long text is folded to a few lines with "Read more"; what you opened stays open. */
const expanded = new Set();
function longText(text, key, cls, limit) {
  text = String(text || "");
  limit = limit || 320;
  const long = text.length > limit || text.split("\n").length > 4;
  const open = expanded.has(key);
  const el = h("div", { class: (cls || "") + (long && !open ? " clamp" : "") }, linkify(text));
  if (!long) return el;
  return h("div", { class: "folded" }, el, h("button", { class: "more-link", type: "button", "aria-expanded": String(open),
    onclick: () => { if (open) expanded.delete(key); else expanded.add(key); render(); } }, open ? "Show less" : "Read more"));
}

function dayLabel(day) {
  const d = new Date();
  const today = d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" }).replace(",", "");
  d.setDate(d.getDate() - 1);
  const yesterday = d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" }).replace(",", "");
  return day === today ? "Today" : day === yesterday ? "Yesterday" : day;
}

function allEvents() {
  const seen = new Set();
  return S.events.concat(cache.older).filter(e => !seen.has(e.id) && seen.add(e.id)).reverse();
}

async function loadEarlier(btn) {
  const all = S.events.concat(cache.older);
  if (!all.length) return;
  busy(btn, true);
  const res = await getJSON("/api/log?before=" + all[all.length - 1].id);
  busy(btn, false);
  const more = res.events || [];
  cache.older = cache.older.concat(more);
  if (more.length < 80) cache.olderDone = true;
  render();
}

function feedView() {
  const inner = h("div", { class: "feed-inner" });
  const events = allEvents();
  if (events.length >= 80 && !cache.olderDone) inner.append(h("div", { class: "earlier" },
    h("button", { class: "ghost small", type: "button", onclick: e => loadEarlier(e.currentTarget) }, "Show earlier messages")));
  if (!S.plan) inner.append(introCard());
  let day = "", cur = null;
  events.forEach(e => {
    const m = say(e);
    if (!m) return;
    if (e.day !== day) { day = e.day; inner.append(h("div", { class: "day", text: dayLabel(day) })); cur = null; }
    if (m.marker) {
      inner.append(h("div", { class: "marker" + (m.you ? " you" : "") }, icon(m.icon || "dot", "sm"), h("span", null, linkify(m.marker)), h("time", { text: e.at })));
      cur = null;
      return;
    }
    if (m.council) {
      inner.append(councilCard(m.council, e, m.text));
      cur = null;
      return;
    }
    const actor = m.actor || e.actor;
    const line = longText(m.text, "ev" + e.id, "line" + (m.tone ? " " + m.tone : ""));
    if (cur && cur.actor === actor && cur.count < 10) { cur.lines.append(line); cur.count++; return; }
    const x = seatOf(actor);
    cur = { actor, count: 1, lines: h("div", { class: "lines" }, line) };
    inner.append(h("article", { class: "msg" }, avatar(actor, null, true),
      h("div", { class: "meta" }, h("strong", { text: displayName(actor) }), x ? h("span", { class: "model", text: prettyModel(x.model) }) : null, h("time", { text: e.at })),
      cur.lines));
  });
  const live = S.seats.filter(x => x.now && (running(x) ? x.runner.state === "working" || ago(x.now.t) < 120 : (x.active || x.live) && ago(x.now.t) < 600));
  if (live.length && !S.project.frozen) inner.append(h("div", { class: "live-now", "aria-live": "off" }, live.map(liveCard)));
  return h("div", { class: "feed", role: "log", "aria-label": "What your AIs are doing" }, inner);
}

const STEP = { think: ["is thinking", "notes"], say: ["says", "send"], run: ["is running a command", "terminal"], edit: ["is editing", "code"],
  read: ["is reading", "search"], tool: ["is using Roundtable", "team"], done: ["finished a step", "check"], error: ["hit a problem", "alert"],
  start: ["is starting", "play"] };
function ago(t) { return t ? Math.max(0, (Date.now() / 1000) - Number(t)) : 1e9; }
function agoText(t) {
  const s = ago(t);
  return s < 45 ? "just now" : s < 3600 ? Math.round(s / 60) + " min ago" : s < 86400 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " days ago";
}

function liveCard(x) {
  const [verb, ic] = STEP[x.now.kind] || ["is working", "dot"];
  const working = running(x) ? x.runner.state === "working" : ago(x.now.t) < 90;
  return h("button", { class: "live", type: "button", title: "See everything " + x.handle + " is doing", onclick: () => go("#/ai/" + x.handle) },
    avatar(x.handle, "sm", true),
    h("span", { class: "live-body" },
      h("span", { class: "live-head" }, h("strong", { text: x.handle }), " ", verb,
        working ? h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")) : h("span", { class: "faint", text: " · " + agoText(x.now.t) })),
      h("span", { class: "live-text" + (x.now.kind === "run" || x.now.kind === "edit" ? " mono" : "") }, x.now.text)),
    icon(ic, "sm"));
}

function introCard() {
  const steps = [
    ["Your AIs talk here", "Every plan, change, test and check shows up in this conversation as it happens."],
    ["Decisions wait above the box", "When something needs you, it's pinned just above where you type, with the buttons that settle it."],
    ["You set the goal", "Type what you want built in the box below. Nothing is built before you approve their plan."],
  ];
  return h("section", { class: "intro" }, h("h2", { text: "How this room works" }),
    h("ol", null, steps.map(([a, b]) => h("li", null, h("strong", { text: a }), h("span", { text: b })))));
}

/* ---------------------------------------------------------------- asking the table */

function councilOf(id) { return (S.councils || []).find(c => c.id === id) || null; }

function memberState(c, m) {
  const failedHere = m.error && [m.answer, m.rank, m.final].includes("failed");
  if (failedHere && (m.answer === "failed" || c.stage !== "answering")) return ["Couldn't: " + fit(plainText(m.error), 90), "bad"];
  if (c.stage === "answering") return m.answer === "done" ? ["Answered", "good"] : ["Answering", "busy"];
  if (c.stage === "ranking") return m.answer !== "done" ? ["No answer", "quiet"] : m.rank === "done" ? ["Ranked the answers", "good"] : ["Ranking the answers", "busy"];
  if (c.stage === "combining") return c.chair === m.seat ? ["Writing the final answer", "busy"] : ["Done", "quiet"];
  if (c.stage === "done") return c.chair === m.seat ? [c.kind === "rescue" ? "Sent its diagnosis" : "Wrote the final answer", "good"]
    : m.answer === "done" ? ["Answered and ranked", "quiet"] : ["No answer", "quiet"];
  return [capital(c.stage), "quiet"];
}

function placeOf(c, seat) {
  const i = (c.ranking || []).findIndex(r => r.seat === seat);
  return i < 0 ? null : i + 1;
}

function councilCard(id, e, fallback) {
  const c = councilOf(id);
  const rescue = (c && c.kind === "rescue") || (e && e.type === "council.rescue");
  const head = h("div", { class: "council-head" }, h("span", { class: "council-mark", "aria-hidden": "true" }, icon(rescue ? "review" : "ask", "sm")),
    h("strong", { text: rescue ? `Second opinion${c && c.task ? " on " + c.task : ""}` : "You asked the table" }),
    c && !["done"].includes(c.stage) ? h("span", { class: "pill " + (c.stage === "failed" ? "stop" : c.stage === "cancelled" ? "" : "work"),
      text: { answering: rescue ? "Looking" : "Answering", ranking: "Ranking", combining: "Combining", failed: "Couldn't answer", cancelled: "Stopped" }[c.stage] || c.stage }) : null,
    e ? h("time", { text: e.at }) : null);
  if (!c) return h("article", { class: "council" }, head, h("p", { class: "muted", text: fallback || id }),
    h("div", { class: "row" }, h("button", { class: "small", type: "button", onclick: () => go("#/council/" + id) }, "Open it")));
  const members = h("ul", { class: "council-members plain" }, c.members.map(m => {
    const [txt, tone] = memberState(c, m);
    const place = c.stage === "done" && c.ranking.length > 1 ? placeOf(c, m.seat) : null;
    return h("li", { class: "cm " + tone }, avatar(m.seat, "sm", true), h("strong", { text: m.seat }),
      h("span", { class: "cm-state" }, txt, tone === "busy" ? h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")) : null),
      place ? h("span", { class: "place p" + place, title: `The others ranked its answer #${place}` }, "#" + place) : null);
  }));
  const kids = [head, rescue ? null : h("div", { class: "council-q" }, longText(c.question, "cq-" + id, "", 260)), members];
  if (c.final) {
    const by = c.chair ? (rescue ? `${c.chair}'s diagnosis` : c.ranking.length > 1 && placeOf(c, c.chair) === 1
      ? `The table's answer, written by ${c.chair}, whose answer the others ranked best` : `The table's answer, written by ${c.chair}`) : "The answer";
    kids.push(h("div", { class: "council-final" }, h("p", { class: "council-by", text: by }),
      longMd(c.final + (c.final_long ? "\n\n…" : ""), "cf-" + id, 900)));
  }
  if (c.stage === "failed" && c.error) kids.push(h("p", { class: "bad-text", text: plainText(c.error) }));
  const actions = [h("button", { class: "small", type: "button", onclick: () => go("#/council/" + id) }, icon("review", "sm"), c.stage === "done" ? "See every answer" : "Watch it")];
  if (c.stage === "done" && !rescue) actions.push(
    h("button", { class: "small", type: "button", onclick: () => askFollowUp(c) }, icon("ask", "sm"), "Ask a follow-up"),
    h("button", { class: "small", type: "button", onclick: () => buildFrom(c) }, icon("plan", "sm"), "Build this"));
  kids.push(h("div", { class: "row" }, actions));
  return h("article", { class: "council" + (rescue ? " rescue" : "") + " st-" + c.stage }, kids);
}

function askFollowUp(c) {
  ui.compose = "ask";
  ui.followUp = c.id;
  close();
  render();
  const el = APP.querySelector("#composer-text");
  if (el) el.focus();
}

function buildFrom(c) {
  ui.compose = "goal";
  close();
  render();
  const el = APP.querySelector("#composer-text");
  if (!el) return;
  el.value = `${c.question}\n\nWhat the AIs agreed on (from ${c.id}):\n${(c.final || "").slice(0, 3200)}`;
  autosize(el);
  el.focus();
  toast("The answer is in the message box", "Edit it into the goal you want, then choose Plan together or Just do it.");
}

/* ---------------------------------------------------------------- what waits for you */

function buildAsks() {
  const asks = [];
  const p = S.plan;
  const skip = k => ["backlog", "no-seats", "no-plan", "not-started"].includes(k) || /^(alert|vote):/.test(k);
  // urgent problems first
  S.alerts.filter(a => a.level >= 4 || (a.level === 3 && a.by !== "human")).forEach(a => {
    const note = h("input", { type: "text", "data-k": "res-" + a.id, placeholder: "What fixed it (optional)", "aria-label": "What fixed it" });
    asks.push({ key: "alert-" + a.id, tone: a.level >= 4 ? "stop" : "", who: a.by, title: `${a.by === "human" ? "You reported" : a.by + " reports"} a ${LEVELS[a.level - 1][1].toLowerCase()}: ${a.title}`,
      body: a.description, extra: h("div", { class: "row" }, note),
      actions: [{ label: "Mark as solved", primary: true, run: b => act("alert.resolve", { id: a.id, resolution: note.value.trim() || "solved by the human" }, { button: b, title: "Marked as solved" }) },
        { label: "Details", go: "alerts" }] });
  });
  S.needs.filter(n => !skip(n.key)).forEach(n => asks.push({ key: n.key, tone: n.tone === "stop" ? "stop" : n.tone === "info" ? "info" : "",
    icon: n.key === "frozen" ? "pause" : n.key.startsWith("plan") || n.key.startsWith("amend") ? "plan" : n.key.startsWith("review") || n.key.startsWith("level") ? "review" : "alert",
    title: plainText(n.title), body: plainText(n.body), actions: n.actions.map(a => ({ label: a.label, primary: a.style === "primary", go: a.go, op: a.op, params: a.params, runSeats: a.run })) }));
  S.votes.filter(v => v.status === "tied").forEach(v => asks.push({ key: "vote-" + v.id, icon: "team", title: "The AIs can't agree: " + v.topic,
    body: v.options.map(o => { const bs = v.ballots.filter(b => b.choice === o); return `${o}: ${bs.map(b => b.seat + (b.reason ? ` (“${b.reason}”)` : "")).join(", ") || "no votes"}`; }).join("\n"),
    actions: v.options.map(o => ({ label: "Choose “" + fit(o, 28) + "”", run: b => act("vote.decide", { id: v.id, choice: o }, { button: b, title: "Decided" }) })) }));
  S.tasks.filter(t => t.status === "backlog").forEach(t => {
    const ready = t.kind === "epic" || (t.files.length && t.proof.length);
    const by = t.filed_by && t.filed_by !== "human" ? t.filed_by : "human";
    asks.push({ key: "found-" + t.id, tone: "info", who: by, title: by === "human" ? `You suggested ${t.id}: ${t.title}` : `${by} found more work: ${t.title}`,
      body: plainText(t.summary) || (ready ? "" : "Before it can start, say which files it may change and how to test it."),
      actions: [ready ? { label: "Add to the work", primary: true, run: b => act("task.accept", { task: t.id }, { button: b, title: "Added " + t.id }) }
        : { label: "Add to the work…", primary: true, go: "task/" + t.id },
      { label: "Not now", run: b => act("task.cancel", { task: t.id, reason: "not needed (decided by the human)" }, { button: b, title: "Set aside " + t.id }) }] });
  });
  S.seats.filter(x => running(x) && x.runner.state === "stuck").forEach(x => asks.push({ key: "stuck-" + x.handle, tone: "", who: x.handle,
    title: `${x.handle} is stuck`, body: plainText(x.runner.error || x.runner.message || ""),
    actions: [{ label: "Try again now", primary: true, run: async b => { busy(b, true); await post("/api/do", { kind: "stop", handle: x.handle }); await special("run", { handle: x.handle }, { button: b, title: "Trying again" }); } },
      { label: "See what it did", go: "ai/" + x.handle }] }));
  const covered = S.needs.some(n => n.key.startsWith("idle:"));
  const fresh = covered ? [] : S.seats.filter(needsStart);
  const runnable = fresh.filter(x => x.can_run && !ui.started[x.handle]);
  if (runnable.length > 1) {
    const names = listWords(runnable.map(x => x.handle));
    asks.push({ key: "start-many", tone: "info", icon: "play", title: `${names} aren't running yet`,
      body: "Let Roundtable run them in the background: it wakes each one whenever there is work, with your own logins. Or open each one in a terminal from its panel on the left.",
      actions: [{ label: "Run them in the background", primary: true, runSeats: runnable.map(x => x.handle) }] });
  }
  fresh.filter(x => !(runnable.length > 1 && runnable.includes(x))).forEach(x => {
    const info = ui.started[x.handle];
    asks.push({ key: "start-" + x.handle, tone: "info", who: x.handle, title: `${x.handle} isn't at the table yet`,
      body: info ? "" : (x.can_run ? "Let Roundtable run it in the background: it wakes it whenever there is work. Or open it in a terminal yourself." : startHint(x)),
      extra: info ? startedBox(x, info) : null,
      actions: x.can_run ? [{ label: "Run in the background", primary: true, runSeats: [x.handle] }, { label: "Open a terminal instead", run: b => startSeat(x, b) }]
        : [{ label: startLabel(x), primary: true, run: b => startSeat(x, b) }, { label: "How to start it", go: "ai/" + x.handle }] });
  });
  return asks;
}

async function runSeats(handles, btn) {
  busy(btn, true);
  const bad = [];
  for (const handle of handles) {
    const res = await post("/api/do", { kind: "run", handle });
    if (!res.ok) bad.push(res);
  }
  busy(btn, false);
  if (bad.length) toast(capital(plainText(bad[0].message)) || "Could not start it", plainText(bad[0].hint || ""), { error: true });
  else toast(handles.length === 1 ? `${handles[0]} now runs in the background` : `${listWords(handles)} now run in the background`,
    "Roundtable wakes them whenever there is work. Watch them at the bottom of the conversation.");
  await refresh(true);
}

function askCard(a) {
  return h("article", { class: "ask" + (a.tone ? " " + a.tone : "") },
    a.who ? avatar(a.who, null, true) : h("span", { class: "badge", "aria-hidden": "true" }, icon(a.icon || "alert", "sm")),
    h("h3", null, linkify(a.title)), a.body ? longText(a.body, "ask-" + a.key, "pre", 260) : null, a.extra || null,
    a.actions && a.actions.length ? h("div", { class: "row" }, a.actions.map(actionButton)) : null);
}

function actionButton(a) {
  const cls = a.primary ? "you small" : "small";
  if (a.go) return h("button", { class: cls, type: "button", onclick: () => go("#/" + a.go) }, a.label);
  if (a.op) return h("button", { class: cls, type: "button", onclick: e => act(a.op, a.params || {}, { button: e.currentTarget }) }, a.label);
  if (a.runSeats) return h("button", { class: cls, type: "button", onclick: e => runSeats(a.runSeats, e.currentTarget) }, icon("play", "sm"), a.label);
  return h("button", { class: cls, type: "button", onclick: e => a.run(e.currentTarget) }, a.label);
}

function asksView() {
  const asks = buildAsks();
  if (!asks.length) return null;
  const urgent = asks.filter(a => a.tone !== "info").length;
  const few = window.matchMedia("(max-width: 760px)").matches ? 1 : 2;
  const shown = ui.allAsks ? asks : asks.slice(0, few);
  return h("section", { class: "waiting", "aria-label": "Waiting for you" }, h("div", { class: "waiting-inner" },
    h("h2", null, icon("dot", "sm"), urgent ? (urgent === 1 ? "1 decision waits for you" : `${urgent} decisions wait for you`) : (asks.length === 1 ? "1 thing to do" : `${asks.length} things to do`)),
    shown.map(askCard),
    asks.length > few ? h("button", { class: "ghost small more-asks", type: "button", onclick: () => { ui.allAsks = !ui.allAsks; render(); } },
      ui.allAsks ? "Show fewer" : `Show ${asks.length - few} more`) : null));
}

/* ---------------------------------------------------------------- the message box */

function autosize(ta) { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight + 2, 200) + "px"; }

const QUICK = { placeholder: "Tell them what to do, like “sol: fix the usage numbers. opus: add a thinking setting”",
  hint: "One AI splits your message into tasks; if you name an AI for a part, it gets that part. Tests and checks still run.", send: "Start" };
const MODES = {
  goal: { placeholder: "What should your AIs build?",
    hint: "Say what, where, and how you'll know it works. They each write a plan without seeing the others', comment on each other's, and bring you one plan.", send: "Start planning" },
  note: { label: "Tell them", placeholder: "Tell your AIs something they should know",
    hint: "Saved as a note every AI reads the next time it checks in.", send: "Send" },
  problem: { label: "Report a problem", placeholder: "What's wrong? The first line is the title",
    hint: "The AIs working nearby must acknowledge it before they take new work.", send: "Report" },
  task: { label: "Add a task", placeholder: "What needs doing?",
    hint: "It waits in your list until you add the files it may change and a test command.", send: "Add" },
  ask: { label: "Ask the table", placeholder: "Ask them anything, like “What is the riskiest part of this code, and why?”", send: "Ask",
    tip: "Every AI answers on its own, they rank each other's answers without names, and the best one writes the final answer.",
    hint: "Each AI answers on its own, then they rank each other's answers without knowing who wrote which, and the best one writes the final answer. They can read your project but change nothing." },
};

function composer() {
  const p = S.plan;
  if (!S.seats.length) return h("footer", { class: "composer" }, h("div", { class: "composer-inner" },
    h("div", { class: "box off" }, h("p", { class: "muted", text: "Add your AIs first. Then you'll give them a goal here." }),
      h("button", { class: "go", type: "button", onclick: () => go("#/welcome") }, icon("plus", "sm"), "Add your AIs"))));
  const live = isLivePlan(p);
  const mode = ui.compose === "ask" ? "ask" : !live ? "goal" : ["note", "problem", "task"].includes(ui.compose) ? ui.compose : "note";
  const quick = ui.planMode === "quick";
  const M = mode === "goal" && quick ? Object.assign({}, MODES.goal, QUICK) : MODES[mode];
  const level = ui.level || S.project.review || "mid";
  const askers = (S.can_ask || []).filter(hd => !ui.askSkip[hd]);
  const ta = h("textarea", { id: "composer-text", class: "grow", "data-k": "composer-" + mode, rows: "1", placeholder: M.placeholder, "aria-label": mode === "goal" ? "The goal" : M.label,
    oninput: e => autosize(e.target),
    onkeydown: e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(sendBtn); } } });
  const sendBtn = h("button", { class: "go send", type: "button", title: M.send, "aria-label": M.send, onclick: e => send(e.currentTarget) },
    icon(mode === "ask" ? "ask" : "send"), mode === "goal" || mode === "ask" ? h("span", { text: M.send }) : null);
  async function send(btn) {
    const text = ta.value.trim();
    if (!text) { ta.focus(); toast(mode === "goal" ? "Write the goal first" : mode === "ask" ? "Write your question first" : "Write something first", mode === "goal" ? "One or two sentences is enough." : ""); return; }
    const first = text.split("\n")[0].trim(), more = text.split("\n").slice(1).join("\n").trim() || null;
    const clear = () => { ta.value = ""; };
    if (mode === "ask") {
      if (!askers.length) { toast("Nobody can answer yet", "Only AIs in Claude Code, Codex or opencode can answer here. Add one, or tick one above."); return; }
      await act("council.ask", { question: text, seats: askers, follow_up: ui.followUp || null }, { button: btn, title: "Asked the table",
        body: askers.length > 1 ? "Each AI answers on its own first, then they rank each other's answers. Watch it in the conversation." : "One AI answers. Add more AIs for a real council.",
        after: () => { clear(); ui.followUp = null; } });
    } else if (mode === "goal") await act("plan.goal", { goal: text, review: level, mode: quick ? "quick" : "full", auto: !!ui.autoLock },
      { button: btn, title: quick ? "On it" : "Planning started", body: quick ? "One AI is splitting it into tasks now" + (ui.autoLock ? "; work starts without asking you." : "; you approve the tasks before work starts.")
        : "Each AI now writes its own plan. If one isn't running, start it and it catches up.", after: clear });
    else if (mode === "note") await act("memory.add", { text }, { button: btn, title: "Sent to your AIs", body: "Saved as a note. Every AI reads it the next time it checks in.", after: clear });
    else if (mode === "problem") await act("alert.raise", { level: 3, title: fit(first, 140), description: more }, { button: btn, title: "Your AIs have been told", body: "The AIs working nearby must acknowledge it before they take new work.", after: clear });
    else await act("task.file", { title: fit(first, 140), summary: more }, { button: btn, title: "Task added", body: "It waits above the message box until you add it to the work.", after: clear });
  }
  const pick = (m, extra) => () => { ui.compose = m; Object.assign(ui, extra || {}); render(); const el = APP.querySelector("#composer-text"); if (el) el.focus(); };
  const kinds = !live
    ? [["full", "Plan together", "Each AI writes a plan, they compare notes and agree on one. Best for bigger changes.", mode === "goal" && !quick, pick("goal", { planMode: "full" })],
      ["quick", "Just do it", "One AI splits your message into tasks and they start. Best when you know what you want.", mode === "goal" && quick, pick("goal", { planMode: "quick" })],
      ["ask", "Ask the table", MODES.ask.tip, mode === "ask", pick("ask")]]
    : [["note", MODES.note.label, MODES.note.hint, mode === "note", pick("note")], ["ask", "Ask the table", MODES.ask.tip, mode === "ask", pick("ask")],
      ["problem", MODES.problem.label, MODES.problem.hint, mode === "problem", pick("problem")], ["task", MODES.task.label, MODES.task.hint, mode === "task", pick("task")]];
  const modes = h("div", { class: "modes" },
    h("div", { class: "seg", role: "group", "aria-label": live ? "What to send" : "How they work" },
      kinds.map(([v, label, tip, on, fn]) => h("button", { type: "button", "aria-pressed": String(on), title: tip, class: v === "ask" ? "ask-seg" : null, onclick: fn },
        v === "ask" ? icon("ask", "sm") : null, label))),
    mode === "goal" ? [h("span", { class: "faint", text: "Checking:" }),
      h("div", { class: "seg", role: "group", "aria-label": "How carefully they check each other's work" },
        ["low", "mid", "high"].map(v => h("button", { type: "button", "aria-pressed": String(v === level), title: CHECKING_TEXT[v], onclick: () => { ui.level = v; render(); } }, CHECKING[v]))),
      h("label", { class: "check small-check", title: "The test commands in the plan run on your computer without you reading them first" },
        h("input", { type: "checkbox", checked: !!ui.autoLock, onchange: e => { ui.autoLock = e.target.checked; render(); } }), h("span", { text: "Start without asking me" }))] : null);
  const who = mode === "ask" ? h("div", { class: "askers" },
    h("span", { class: "faint", text: (S.can_ask || []).length ? "Who answers:" : "Only AIs in Claude Code, Codex or opencode can answer here." }),
    (S.can_ask || []).map(hd => h("button", { type: "button", class: "chip", "aria-pressed": String(!ui.askSkip[hd]), title: prettyModel((seatOf(hd) || {}).model),
      onclick: () => { if (ui.askSkip[hd]) delete ui.askSkip[hd]; else ui.askSkip[hd] = true; render(); } }, avatar(hd, "xs", true), hd)),
    ui.followUp ? h("span", { class: "chip on-follow" }, icon("ask", "sm"), "Following up on " + ui.followUp,
      h("button", { type: "button", class: "chip-x", "aria-label": "Not a follow-up", onclick: () => { ui.followUp = null; render(); } }, icon("x", "sm"))) : null) : null;
  return h("footer", { class: "composer" + (mode === "ask" ? " asking" : "") }, h("div", { class: "composer-inner" }, modes, who,
    h("div", { class: "box" }, ta, sendBtn),
    h("p", { class: "hint", text: M.hint + (mode === "goal" ? (ui.autoLock ? " Work starts without asking you: you won't read the test commands first." : " Nothing is built before you approve it.")
      : " Enter sends; Shift+Enter starts a new line.") })));
}

/* ---------------------------------------------------------------- the plan, on the right */

function planSide() {
  const p = S.plan;
  const kids = [];
  if (!isLivePlan(p)) {
    kids.push(h("div", { class: "stack tight" }, h("h2", { text: "How it goes" }), journeySteps()));
    if (p) kids.push(h("p", { class: "faint", text: `Last goal (${p.stage === "done" ? "finished" : "cancelled"}): ${fit(p.goal, 160)}` }));
  } else {
    kids.push(h("div", { class: "stack tight" }, h("h2", { text: p.mode === "quick" ? "The goal (just do it)" : "The goal" }), longText(p.goal, "goal-side", "goal", 220)));
    if (p.stage !== "locked") kids.push(h("div", { class: "stack tight" }, h("h2", { text: "Planning" }), planSteps(p),
      h("button", { class: p.stage === "awaiting_human" ? "you" : "", type: "button", onclick: () => go("#/plan") }, icon("plan", "sm"),
        p.stage === "awaiting_human" ? "Read and approve the plan" : "Read their plans")));
    else kids.push(progressBlock(), taskGroups(6));
  }
  const found = S.tasks.filter(t => t.status === "backlog").length;
  if (found) kids.push(h("button", { class: "small", type: "button", onclick: () => go("#/found") }, `Work your AIs found (${found})`));
  kids.push(h("nav", { class: "side-links", "aria-label": "More" },
    [["council", "ask", "Questions"], ["usage", "usage", "Usage"], ["notes", "notes", "Notes"], ["history", "history", "History"], ["alerts", "alert", "Problems"]].map(([r, ic, label]) =>
      h("button", { class: "ghost small", type: "button", onclick: () => go("#/" + r) }, icon(ic, "sm"), label + (r === "alerts" && S.alerts.length ? ` (${S.alerts.length})` : "")))));
  return h("aside", { class: "plan-side", "aria-label": "The plan" }, kids);
}

function journeySteps() {
  const seats = S.seats, p = S.plan;
  const started = seats.length && seats.filter(x => x.status === "active").every(x => running(x) || x.active || x.live);
  const live = isLivePlan(p);
  const steps = [
    ["Choose your AIs", "Two or more, from different companies, so they catch each other's mistakes.", seats.length > 0],
    ["Start them", "Run them in the background, or open each one in its own app.", !!started],
    ["Give them a goal", "In the box at the bottom of the conversation.", !!live],
    ["Approve their plan", "Nothing is built before you say yes.", !!(live && p.stage === "locked")],
    ["They build and check", "Every task is tested, checked by another AI, then merged.", false],
  ];
  const at = steps.findIndex(x => !x[2]);
  return h("ol", { class: "steps" }, steps.map(([a, b, done], i) => h("li", { class: done ? "done" : i === at ? "now" : "", "aria-current": i === at ? "step" : null },
    h("span", { class: "tick", "aria-hidden": "true" }, done ? icon("check", "sm") : null), h("div", null, h("strong", { text: a }), h("small", { text: b })))));
}

function stageNote(p, id) {
  const people = p.people;
  const idle = h => { const x = seatOf(h); return x && idleSeat(x); };
  if (id === "drafting") return people.filter(x => x.planner).map(x => `${x.seat} ${x.drafted ? "done" : idle(x.seat) ? "not running" : "writing"}`).join(", ");
  if (id === "merging" && p.chair && idle(p.chair) && p.stage === "merging") return `${p.chair} isn't running`;
  if (id === "critique") { const done = people.reduce((n, x) => n + x.critiques_done, 0), all = people.reduce((n, x) => n + x.critiques, 0); return all ? `${done} of ${all} comments in` : ""; }
  if (id === "merging") return p.chair ? `${p.chair} combines them` : "";
  if (id === "proposed") { const voters = people.filter(x => !x.chair); return voters.length ? `${voters.filter(x => x.approval && x.approval.decision === "approve").length} of ${voters.length} agreed` : ""; }
  if (id === "awaiting_human") return p.stage === "awaiting_human" ? `${plural(p.tasks.length, "task")}, ready for you` : "";
  return "";
}

function planSteps(p) {
  const steps = p.mode === "quick"
    ? [["merging", "One AI splits it into tasks"]].concat(p.auto ? [] : [["awaiting_human", "You approve it"]], [["locked", "They build it"]])
    : STAGE_STEPS;
  const at = steps.findIndex(x => x[0] === (p.stage === "voting" ? "proposed" : p.stage));
  return h("ol", { class: "steps" }, steps.map(([id, label], i) => {
    const note = i <= at ? stageNote(p, id) : "";
    return h("li", { class: i < at ? "done" : i === at ? "now" : "", "aria-current": i === at ? "step" : null },
      h("span", { class: "tick", "aria-hidden": "true" }, i < at ? icon("check", "sm") : null),
      h("div", null, h("strong", { text: label }), note ? h("small", { text: note }) : null));
  }));
}

function progressBlock() {
  const pr = progress(S);
  const bar = h("div", { class: "bar", role: "img", "aria-label": `${pr.done} of ${pr.total} done, ${pr.active} in progress` });
  const done = h("i", { class: "done" }), going = h("i", { class: "going" });
  done.style.width = pr.total ? (100 * pr.done / pr.total) + "%" : "0";
  going.style.width = pr.total ? (100 * pr.active / pr.total) + "%" : "0";
  bar.append(done, going);
  return h("div", { class: "stack tight" }, h("h2", { text: "Progress" }), bar,
    h("p", { class: "faint", text: `${pr.done} done, ${pr.active} in progress, ${pr.total - pr.done - pr.active} to go` }));
}

function taskStatus(t) {
  if (t.status === "open") return t.waits_for.length ? "after " + t.waits_for.join(", ") : "waiting";
  if (t.status === "in_review") return t.reviewers.length ? "checked by " + listWords(t.reviewers) : "being checked";
  if (t.status === "ready") return "ready to start";
  return (t.owner && t.status === "claimed" ? t.owner + " is building it" : t.status_label.toLowerCase());
}
const DOT = { claimed: "work", changes_requested: "you", proving: "work", in_review: "work", merge_blocked: "you", done: "ok", open: "hollow", ready: "hollow", backlog: "you", cancelled: "hollow" };

function taskButton(t) {
  return h("li", null, h("button", { type: "button", onclick: () => go("#/task/" + t.id) },
    h("span", { class: "dot " + (DOT[t.status] || "hollow"), "aria-hidden": "true" }),
    h("span", { class: "t" + (t.status === "done" ? " done" : "") }, h("strong", { text: t.title }), h("span", { text: `${t.id} · ${taskStatus(t)}` }))));
}

function taskGroups(limitDone) {
  const real = S.tasks.filter(t => t.kind !== "epic" && !["cancelled", "backlog"].includes(t.status));
  const groups = [
    ["Now", real.filter(t => ACTIVE.includes(t.status))],
    ["Next", real.filter(t => ["open", "ready"].includes(t.status))],
    ["Done", real.filter(t => t.status === "done").reverse()],
  ];
  return h("div", { class: "stack tight" }, groups.filter(g => g[1].length).map(([label, list]) => {
    const cut = label === "Done" && !ui.showDone && limitDone ? list.slice(0, limitDone) : list;
    return h("div", { class: "stack tight" }, h("h2", { text: `${label} (${list.length})` }), h("ul", { class: "tasklist" }, cut.map(taskButton)),
      cut.length < list.length ? h("button", { class: "ghost small", type: "button", onclick: () => { ui.showDone = true; render(); } }, `Show all ${list.length}`) : null);
  }));
}

/* ---------------------------------------------------------------- panels that open over the room */

PAGES.room = () => null;

function drawer(page, fresh) {
  const view = PAGES[page](S) || {};
  const id = "drawer-title";
  const panel = h("aside", { class: "drawer" + (fresh ? "" : " still") + (view.wide ? " wide" : ""), role: "dialog", "aria-modal": "true", "aria-labelledby": id },
    h("header", { class: "drawer-head" },
      view.back ? h("button", { class: "ghost icon-only", type: "button", "aria-label": "Back", title: "Back", onclick: () => go(view.back) }, icon("back")) : null,
      h("h1", { id, text: view.title || "" }),
      h("button", { class: "ghost icon-only", type: "button", "aria-label": "Close", title: "Close (Esc)", onclick: close }, icon("x"))),
    h("div", { class: "drawer-body" }, h("div", { class: "stack" }, view.body)));
  return [h("div", { class: "scrim" + (fresh ? "" : " still"), onclick: close }), panel];
}

function sec(title, ...body) {
  return h("section", { class: "section" }, title ? h("h2", { text: title }) : null, body);
}
function note(text, tone) { return h("p", { class: "box" + (tone ? " " + tone : ""), text }); }

/* ---------------------------------------------------------------- plan */

PAGES.plan = st => {
  const p = st.plan;
  if (!isLivePlan(p)) return { title: "Give your AIs a goal", body: [goalForm(st),
    p ? h("p", { class: "faint", text: `Last goal (${p.stage === "done" ? "finished" : "cancelled"}): ${p.goal}` }) : null] };
  const approving = p.stage === "awaiting_human" || (["proposed", "voting"].includes(p.stage) && p.tasks.length);
  const body = [
    h("div", { class: "box" }, h("p", { class: "faint", text: p.mode === "quick" ? "The goal (just do it" + (p.auto ? ", no approval)" : ")") : "The goal" }), longText(p.goal, "goal-plan", "goal", 600)),
    p.stage === "awaiting_human" ? approveBlock(p, false) : null,
  ];
  if (p.stage === "locked") body.push(sec(null, progressBlock(), taskGroups(0)));
  else body.push(sec(p.stage_label, h("p", { class: "faint", text: `Since ${p.since}.` + (p.revisions ? ` Revised ${plural(p.revisions, "time")}.` : "") }), planSteps(p),
    peopleList(p),
    p.overdue ? h("div", { class: "box warn stack tight" }, h("p", { text: "Some plans are late. You can go on with the ones that are in." }),
      h("div", { class: "row" }, h("button", { class: "you", type: "button", onclick: e => act("plan.continue", {}, { button: e.currentTarget }) }, "Go on without them"))) : null));
  if (approving && p.stage !== "awaiting_human") body.push(approveBlock(p, true));
  if (p.proposal || p.tasks.length) {
    const inner = [p.proposal ? h("p", { class: "pre", text: p.proposal }) : null, specList(p.tasks)];
    body.push(p.stage === "locked"
      ? h("details", { class: "section", "data-k": "plan-text" }, h("summary", null, icon("chevron", "sm"), "The approved plan"), inner)
      : sec(p.proposal ? "The combined plan" : "The plan", p.chair ? h("p", { class: "faint", text: `Combined by ${p.chair}.` }) : null, inner));
  }
  if (p.drafts.length) body.push(sec("Each AI's own plan",
    h("p", { class: "faint", text: p.stage === "drafting" ? "The AIs can't see each other's plans until every plan is in. You can." : "The AIs saw these as Plan A, B, C, without names." }),
    p.drafts.map(d => draftBlock(d, p))));
  if (p.amendments.length) body.push(note(`${plural(p.amendments.length, "change")} to the approved plan ${p.amendments.length === 1 ? "is" : "are"} waiting; you'll find ${p.amendments.length === 1 ? "it" : "them"} above the message box.`));
  body.push(cancelPlanBlock(p));
  return { title: p.stage === "awaiting_human" ? "Approve the plan" : "The plan", body };
};

function peopleList(p) {
  if (!p.people.length) return null;
  return h("ul", { class: "list" }, p.people.map(x => h("li", { class: "row" }, avatar(x.seat, "sm", true),
    h("strong", { text: x.seat }), x.chair ? h("span", { class: "pill", text: "combines the plans" }) : null,
    h("span", { class: "muted", text: [
      x.planner ? (x.drafted ? "wrote a plan" : "writing a plan…") : null,
      x.critiques ? `commented on ${x.critiques_done} of ${x.critiques}` : null,
      x.approval ? (x.approval.decision === "approve" ? "agreed" : "objected" + (x.approval.reason ? `: ${x.approval.reason}` : "")) : null,
    ].filter(Boolean).join(", ") || "waiting" }))));
}

function approveBlock(p, early) {
  const ack = h("input", { type: "checkbox", id: "lock-ack", "data-k": "lock-ack" });
  const btn = h("button", { class: "you", type: "button", onclick: e => {
    if (!ack.checked) { toast("Tick the box first", "These commands will run on your computer. Read them, then tick the box."); return; }
    act("plan.lock", early ? { force: true } : {}, { button: e.currentTarget, title: "Plan approved. The AIs start building.", after: () => go("#/room") });
  } }, icon("check", "sm"), early ? "Approve without waiting" : "Approve the plan");
  const body = [
    early ? h("p", { class: "muted", text: "Not every AI has agreed yet. You can approve anyway; their objections are listed above." })
      : h("p", { text: `Your AIs agreed on ${plural(p.tasks.length, "task")}. When you approve, they start building, and after each task Roundtable runs its test command on your computer to prove the work is right.` }),
    h("div", { class: "stack tight" }, h("strong", { text: "These commands will run on your computer" }),
      h("div", { class: "output", text: p.commands.length ? p.commands.join("\n") : "(no commands)" })),
    h("label", { class: "check", for: "lock-ack" }, ack, h("span", null, "I've read these commands and they are safe to run here")),
    h("div", { class: "row" }, btn)];
  if (early) return h("details", { class: "section", "data-k": "approve-early" }, h("summary", null, icon("chevron", "sm"), "Approve now, without waiting for every AI"), h("div", { class: "stack" }, body));
  return h("section", { class: "ask decide-block" }, h("span", { class: "badge", "aria-hidden": "true" }, icon("plan", "sm")), h("h3", { text: "Your decision" }), h("div", { class: "stack" }, body));
}

function specList(specs) {
  if (!specs || !specs.length) return null;
  return h("ol", { class: "stack tight plain" }, specs.map((t, i) => h("li", { class: "taskcard" },
    h("div", { class: "row" }, h("strong", { text: `${i + 1}. ${t.title}` }), t.kind && t.kind !== "task" ? h("span", { class: "pill", text: t.kind }) : null,
      t.priority !== undefined && t.priority < 2 ? h("span", { class: "pill you", text: PRIORITY[t.priority] }) : null),
    t.summary ? h("p", { class: "muted", text: t.summary }) : null,
    h("dl", { class: "kv" },
      h("dt", { text: "Who" }), h("dd", { text: t.owner || "whichever AI is free" }),
      t.depends_on && t.depends_on.length ? [h("dt", { text: "After" }), h("dd", { text: "step " + t.depends_on.join(", ") })] : null,
      (t.files || []).length ? [h("dt", { text: "Files" }), h("dd", { class: "mono", text: t.files.join(", ") })] : null,
      (t.proof || []).length ? [h("dt", { text: "Tested by" }), h("dd", { class: "mono", text: t.proof.join(" && ") })] : null))));
}

function draftBlock(d, p) {
  const crits = p.critiques.filter(c => c.draft === d.label);
  return h("details", { class: "taskcard", "data-k": "draft-" + (d.label || d.author) },
    h("summary", null, icon("chevron", "sm"), avatar(d.author, "sm", true), h("span", null, d.label ? `Plan ${d.label}, by ${d.author}` : `Plan by ${d.author}`),
      h("span", { class: "faint", text: `${plural(d.tasks.length, "task")}, ${plural(crits.length, "comment")}` })),
    h("p", { class: "pre", text: d.text }), specList(d.tasks),
    crits.map(c => h("div", { class: "box stack tight" }, h("strong", { text: `Comments from ${c.critic}` }),
      h("ul", { class: "plain stack tight" }, c.points.map(pt => h("li", null,
        h("span", { class: "pill " + ({ keep: "ok", drop: "stop" }[pt.verdict] || "work"), text: ({ keep: "Keep", change: "Change", drop: "Drop" }[pt.verdict] || capital(pt.verdict || "Note")) }), " ", pt.text))))));
}

function cancelPlanBlock(p) {
  if (!ui.cancelPlan) return h("div", { class: "row" }, h("button", { class: "ghost danger", type: "button", onclick: () => { ui.cancelPlan = true; render(); } }, "Cancel this plan…"));
  const reason = h("input", { type: "text", id: "cancel-reason", "data-k": "cancel-reason", placeholder: "Why (the AIs will read this)" });
  return sec("Cancel the plan", h("p", { class: "muted", text: "Unfinished tasks are cancelled too. Work already merged stays." }),
    h("div", { class: "field" }, h("label", { for: "cancel-reason", text: "Reason" }), reason),
    h("div", { class: "row" }, h("button", { class: "danger", type: "button", onclick: e => {
      if (!reason.value.trim()) { toast("Add a reason", "The AIs read it, so they know what changed."); return; }
      act("plan.cancel", { reason: reason.value.trim() }, { button: e.currentTarget, after: () => { ui.cancelPlan = false; } });
    } }, "Cancel the plan"), h("button", { type: "button", onclick: () => { ui.cancelPlan = false; render(); } }, "Keep it")));
}

function goalForm(st, after) {
  if (!st.seats.length) return h("div", { class: "stack" }, h("p", { class: "muted", text: "A plan needs AIs to write it. Add two or more, ideally from different companies." }),
    h("div", { class: "row" }, h("button", { class: "go", type: "button", onclick: () => go("#/welcome") }, icon("plus", "sm"), "Add your AIs")));
  const planners = st.seats.filter(x => x.status === "active" && x.roles.includes("plan"));
  const goal = h("textarea", { id: "goal", "data-k": "goal", rows: "5", placeholder: "Add a search box to the log page. It should ignore upper and lower case, and come with tests." });
  const level = st.project.review;
  return h("div", { class: "stack" },
    h("div", { class: "field" }, h("label", { for: "goal", text: "What should your AIs build?" }),
      h("span", { class: "help", text: "Be specific: what, where, and how you will know it works." }), goal),
    h("div", { class: "examples", "aria-label": "Examples" }, [
      "Add a dark mode switch to the settings page, with tests.",
      "Find and fix the bug that makes login fail on Safari.",
      "Write a README that explains how to install and run this project.",
    ].map(x => h("button", { type: "button", onclick: () => { goal.value = x; goal.focus(); } }, x))),
    h("fieldset", { class: "field" }, h("legend", { text: "How should they work?" }),
      h("div", { class: "choices" }, [["full", "Plan together", "Each AI writes a plan without seeing the others', they comment on each other's and agree on one. Best for bigger changes."],
        ["quick", "Just do it", "One AI splits your goal into tasks and they start. Best when you already know what you want, like “sol: do X, opus: do Y”."]].map(([v, label, text]) =>
        h("label", { class: "choice" }, h("input", { type: "radio", name: "pmode", value: v, "data-k": "pmode-" + v, checked: v === (ui.planMode || "full") }),
          h("div", null, h("strong", { text: label }), h("span", { text })))))),
    h("label", { class: "check" }, h("input", { type: "checkbox", id: "auto-lock", "data-k": "auto-lock" }),
      h("span", null, h("strong", { text: "Start without asking me" }), h("span", { class: "help", text: " Skip approving the plan. Its test commands run on your computer without you reading them first." }))),
    h("fieldset", { class: "field" }, h("legend", { text: "How carefully should they check each other's work?" }),
      h("div", { class: "choices" }, ["low", "mid", "high"].map(v => h("label", { class: "choice" },
        h("input", { type: "radio", name: "level", value: v, "data-k": "level-" + v, checked: v === level }),
        h("div", null, h("strong", { text: CHECKING[v] + (v === "mid" ? " (recommended)" : "") }), h("span", { text: CHECKING_TEXT[v] })))))),
    planners.length > 1 ? h("details", { "data-k": "planners" }, h("summary", null, icon("chevron", "sm"), `Who writes a plan (${planners.length > 3 ? "up to three" : "all of them"})`),
      h("div", { class: "row" }, planners.map((x, i) => h("label", { class: "check" },
        h("input", { type: "checkbox", "data-k": "planner-" + x.handle, value: x.handle, checked: i < 3, class: "planner" }),
        h("span", null, h("strong", { text: x.handle }), " ", h("span", { class: "faint", text: prettyModel(x.model) })))))) : null,
    !planners.length ? note("None of your AIs is set to write plans. Open one of them on the left to change that.", "warn") : null,
    h("div", { class: "row" }, h("button", { class: "go", type: "button", onclick: e => {
      const text = goal.value.trim();
      if (!text) { toast("Write the goal first", "One or two sentences is enough."); goal.focus(); return; }
      const picked = [...APP.querySelectorAll("input.planner:checked")].map(x => x.value);
      const lv = (APP.querySelector('input[name="level"]:checked') || {}).value;
      const pm = (APP.querySelector('input[name="pmode"]:checked') || {}).value || "full";
      const auto = !!(APP.querySelector("#auto-lock") || {}).checked;
      act("plan.goal", { goal: text, planners: pm === "quick" ? null : (picked.length ? picked : null), review: lv, mode: pm, auto }, { button: e.currentTarget, title: "Planning started", body: "Each AI now writes its own plan. If one isn't started yet, start it and it catches up.", after: after || (() => go("#/room")) });
    } }, icon("send", "sm"), "Start planning")));
}

/* ---------------------------------------------------------------- a question to the table */

const ORD = n => n + (n % 10 === 1 && n % 100 !== 11 ? "st" : n % 10 === 2 && n % 100 !== 12 ? "nd" : n % 10 === 3 && n % 100 !== 13 ? "rd" : "th");

PAGES.council = st => {
  const id = (route.sub || "").toUpperCase();
  if (!id) return { title: "Questions to the table", body: [
    h("p", { class: "muted", text: "Ask from the message box: every AI answers on its own, they rank each other's answers without names, and the one the others ranked best writes the final answer. Second opinions on failing tasks show up here too." }),
    (st.councils || []).length ? h("ul", { class: "tasklist" }, st.councils.map(c => h("li", null, h("button", { type: "button", onclick: () => go("#/council/" + c.id) },
      h("span", { class: "dot " + (c.stage === "done" ? "ok" : c.stage === "failed" ? "stop" : c.stage === "cancelled" ? "hollow" : "work"), "aria-hidden": "true" }),
      h("span", { class: "t" }, h("strong", { text: c.kind === "rescue" ? `Second opinion on ${c.task}` : fit(c.question, 120) }),
        h("span", { text: `${c.id} · ${c.at} · ${c.members.map(m => m.seat).join(", ")}` }))))))
      : note("No questions yet. Choose “Ask the table” in the message box.")] };
  const d = cache.council[id];
  if (!d) { loadCouncil(id).then(render); return { title: id, back: "#/council", body: h("p", { class: "muted", text: "Loading…" }) }; }
  if (d.ok === false) return { title: id, back: "#/council", body: note(plainText(d.message) || "There is no such question.") };
  const rescue = d.kind === "rescue";
  const answers = d.parts.filter(x => x.stage === "answer");
  const ranks = d.parts.filter(x => x.stage === "rank");
  const stepsDef = rescue ? [["answering", "It reads the failure and the code"], ["done", "It sends the builder a diagnosis"]]
    : [["answering", "Each AI answers on its own"], ["ranking", "They rank the answers, without names"], ["combining", "The best one writes the final answer"], ["done", "Answered"]];
  const at = d.stage === "done" ? stepsDef.length : stepsDef.findIndex(x => x[0] === d.stage);
  const steps = h("ol", { class: "steps" }, stepsDef.map(([sid, label], i) => h("li", { class: i < at || d.stage === "done" ? "done" : i === at ? "now" : "" },
    h("span", { class: "tick", "aria-hidden": "true" }, i < at || d.stage === "done" ? icon("check", "sm") : null), h("div", null, h("strong", { text: label })))));
  const labelSeat = Object.fromEntries(answers.map(a => [a.label, a.seat]));
  const body = [
    h("div", { class: "box" }, h("p", { class: "faint", text: rescue ? `Asked by Roundtable after ${d.task} failed its tests twice` : `You asked ${d.members.join(", ")} at ${d.at}` }),
      rescue ? h("p", { class: "goal", text: d.question }) : longText(d.question, "cqd-" + id, "goal", 600)),
    ["done", "failed", "cancelled"].includes(d.stage) ? null : sec(null, steps),
  ];
  if (d.final) body.push(sec(rescue ? `${d.chair}'s diagnosis` : "The table's answer", d.chair && !rescue ? h("p", { class: "faint", text: `Written by ${d.chair}${d.ranking.length > 1 && d.ranking[0].seat === d.chair ? ", whose answer the others ranked best" : ""}, from every answer and review.` }) : null,
    md(d.final)));
  if (d.error) body.push(note(plainText(d.error), d.stage === "failed" ? "warn" : ""));
  if (d.ranking && d.ranking.length > 1) body.push(sec("How they ranked each other",
    h("p", { class: "muted", text: "Each AI saw the answers as Answer A, B, C, in random order and without names, and ranked them all, its own included." }),
    h("ol", { class: "ranking plain" }, d.ranking.map((r, i) => h("li", { class: "rk" + (i === 0 ? " first" : "") },
      h("span", { class: "place p" + (i + 1), text: "#" + (i + 1) }), avatar(r.seat, "sm", true),
      h("span", { class: "rk-who" }, h("strong", { text: r.seat }), h("span", { class: "faint", text: `Answer ${r.label} · ${prettyModel((seatOf(r.seat) || {}).model || "")}` })),
      h("span", { class: "rk-score", title: "Average place it was given (1 is best)" }, r.avg != null ? `average place ${r.avg}` : "not ranked",
        r.firsts ? h("span", { class: "faint", text: ` · ranked first by ${plural(r.firsts, "AI")}` }) : null))))));
  if (answers.length) body.push(sec(rescue ? "What it found" : "Every answer", answers.map(a => {
    const place = (d.ranking || []).findIndex(r => r.seat === a.seat) + 1;
    return h("details", { class: "taskcard", "data-k": `ans-${id}-${a.seat}`, open: answers.length === 1 ? true : null },
      h("summary", null, icon("chevron", "sm"), avatar(a.seat, "sm", true),
        h("span", null, rescue ? a.seat : `Answer ${a.label || "?"}, by ${a.seat}`),
        a.status === "running" ? h("span", { class: "pill work", text: "answering" }) : a.status === "failed" ? h("span", { class: "pill stop", text: "couldn't answer" })
          : place && d.ranking.length > 1 ? h("span", { class: "pill" + (place === 1 ? " ok" : ""), text: `ranked ${ORD(place)}` }) : null,
        h("span", { class: "faint", text: [a.seconds ? `${Math.round(a.seconds)} s` : "", a.tokens ? `${num(a.tokens)} tokens` : ""].filter(Boolean).join(" · ") })),
      a.error ? note(plainText(a.error), "warn") : md(a.text));
  })));
  if (ranks.length) body.push(sec("Their reviews", ranks.map(r => h("details", { class: "taskcard", "data-k": `rev-${id}-${r.seat}` },
    h("summary", null, icon("chevron", "sm"), avatar(r.seat, "sm", true), h("span", null, `${r.seat}'s review`),
      r.ranking.length ? h("span", { class: "faint", text: r.ranking.map(l => labelSeat[l] || l).join(" > ") }) : r.status === "running" ? h("span", { class: "pill work", text: "ranking" }) : null),
    r.error ? note(plainText(r.error), "warn") : md(String(r.text || "").split("FINAL RANKING:")[0])))));
  const actions = [];
  if (d.stage === "done" && !rescue) actions.push(h("button", { type: "button", onclick: () => askFollowUp(d) }, icon("ask", "sm"), "Ask a follow-up"),
    h("button", { class: "go", type: "button", onclick: () => buildFrom(d) }, icon("plan", "sm"), "Build this"));
  if (!["done", "failed", "cancelled"].includes(d.stage)) actions.push(h("button", { class: "danger", type: "button",
    onclick: e => act("council.cancel", { id }, { button: e.currentTarget, title: "Stopped", after: () => { delete cache.council[id]; } }) }, "Stop it"));
  if (actions.length) body.push(h("div", { class: "row" }, actions));
  body.push(h("p", { class: "faint", text: `${num(d.tokens)} tokens in all. They could read your project but not change it.` }));
  return { title: rescue ? `Second opinion on ${d.task}` : "A question to the table", back: "#/council", wide: true, body };
};

/* ---------------------------------------------------------------- one task */

PAGES.task = st => {
  const id = taskRoute();
  const d = cache.task[id];
  if (!id) return { title: "Task", body: h("p", { class: "muted", text: "No task chosen." }) };
  if (!d) { loadTask(id).then(render); return { title: id, body: h("p", { class: "muted", text: "Loading…" }) }; }
  if (d.ok === false) return { title: id, body: h("p", { class: "muted", text: plainText(d.message) || "There is no such task." }) };
  const builders = st.seats.filter(x => x.roles.includes("build") && x.status === "active");
  const body = [h("div", { class: "row" }, h("span", { class: "pill " + ({ done: "ok", backlog: "you", merge_blocked: "you", changes_requested: "you", cancelled: "" }[d.status] || "work"), text: d.status_label }),
    h("span", { class: "faint", text: d.id + (d.kind !== "task" ? " · " + d.kind : "") + (d.priority !== 2 ? ` · ${PRIORITY[d.priority].toLowerCase()} priority` : "") }),
    d.labels.map(l => h("span", { class: "pill", text: l })))];
  if (d.status === "backlog") body.push(h("section", { class: "ask decide-block" }, avatar(d.filed_by || "human", null, true),
    h("h3", { text: d.filed_by && d.filed_by !== "human" ? `${d.filed_by} found this while working` : "You suggested this" }),
    h("p", { text: "Add it to the work, or set it aside." }), acceptForm(d, builders)));
  if (d.status === "merge_blocked") body.push(h("div", { class: "box warn stack tight" }, h("p", { text: plainText(d.merge_note) || "Approved, but it can't be merged yet." }),
    h("div", { class: "row" }, h("button", { class: "you", type: "button", onclick: e => act("task.merge", { task: d.id }, { button: e.currentTarget }) }, "Try the merge again"))));
  if (st.reviews.some(r => r.task === d.id)) body.push(h("div", { class: "row" }, h("button", { class: "you", type: "button", onclick: () => go("#/review/" + d.id) }, icon("review", "sm"), "Check its changes")));
  if (d.summary) body.push(h("p", { class: "pre", text: plainText(d.summary) }));
  body.push(h("dl", { class: "kv" },
    h("dt", { text: "Who" }), h("dd", { text: d.owner || "whichever AI is free" }),
    d.filed_by ? [h("dt", { text: "Added by" }), h("dd", { text: who(d.filed_by) })] : null,
    h("dt", { text: "Checking" }), h("dd", { text: CHECKING[d.review] || d.review }),
    h("dt", { text: "Files" }), h("dd", { class: "mono", text: d.files.join(", ") || "-" }),
    h("dt", { text: "Tested by" }), h("dd", { class: "mono", text: d.proof.join(" && ") || "-" }),
    d.waits_for.length ? [h("dt", { text: "After" }), h("dd", null, d.waits_for.map(x => [h("a", { class: "tid", href: "#/task/" + x, text: x }), " "]))] : null,
    d.links.filter(l => l.kind !== "waits_for").length ? [h("dt", { text: "Linked" }), h("dd", null, d.links.filter(l => l.kind !== "waits_for").map(l => h("span", null, l.kind.replace(/_/g, " ") + " ", h("a", { class: "tid", href: "#/task/" + l.other, text: l.other }), " ")))] : null,
    d.parent ? [h("dt", { text: "Part of" }), h("dd", null, h("a", { class: "tid", href: "#/task/" + d.parent, text: d.parent }), " ", (taskOf(d.parent) || {}).title || "")] : null));
  if (d.children.length) body.push(sec("Tasks in this group", h("ul", { class: "tasklist" }, d.children.map(c => taskButton(Object.assign({ waits_for: [], reviewers: [], status_label: "", owner: "" }, taskOf(c.id) || c))))));
  if (d.proofs.length) body.push(sec("Test runs", d.proofs.slice(0, 3).map(p => h("div", { class: "stack tight" },
    h("div", { class: "row" }, h("span", { class: "pill " + (p.status === "passed" ? "ok" : ["running", "queued"].includes(p.status) ? "work" : "stop"), text: { passed: "Passed", failed: "Failed", running: "Running", queued: "Queued" }[p.status] || p.status }),
      h("span", { class: "faint", text: `${p.at}, for ${p.by}` })),
    p.output ? h("div", { class: "output", text: p.output }) : null))));
  if (d.checkpoints.length) body.push(sec("Progress notes", h("ul", { class: "list" }, d.checkpoints.slice(0, 8).map(c => h("li", null,
    h("p", null, h("strong", { text: c.seat + ": " }), c.line), h("p", { class: "faint", text: `${c.at}${c.files.length ? `, ${plural(c.files.length, "file")} +${c.added} -${c.removed}` : ""}` }))))));
  if (d.reviews.length) body.push(sec("Checks by other AIs", h("ul", { class: "list" }, d.reviews.map(r => h("li", { class: "stack tight" },
    h("div", { class: "row" }, h("strong", { text: displayName(r.reviewer) }), h("span", { class: "pill " + (r.verdict === "approve" ? "ok" : r.verdict === "changes" ? "you" : "work"), text: r.verdict === "approve" ? "approved" : r.verdict === "changes" ? "asked for changes" : "checking" }),
      h("span", { class: "faint", text: `${(CHECKING[r.level] || r.level)} checking, round ${r.round}` })),
    r.points.length ? h("ul", null, r.points.map(p => h("li", { text: typeof p === "string" ? p : (p.text || JSON.stringify(p)) }))) : null)))));
  if (d.comments.length) body.push(sec("Comments on lines", h("ul", { class: "list" }, d.comments.map(c => h("li", null,
    h("p", { class: "mono", text: `${c.file}${c.line ? ":" + c.line : ""}` }), h("p", { text: c.text }), c.reply ? h("p", { class: "muted", text: "Reply: " + c.reply }) : null)))));
  if (d.changed.length) body.push(sec("Files changed", h("ul", { class: "list" }, d.changed.map(c => h("li", { class: "mono" }, c.path, h("span", { class: "faint", text: `  +${c.added} -${c.removed}` })))),
    h("div", { class: "row" }, h("button", { class: "small", type: "button", onclick: () => go("#/review/" + d.id) }, icon("review", "sm"), "See the changes"))));
  if (d.events.length) body.push(sec("What happened", h("ul", { class: "list" }, d.events.map(e => { const m = say(e); return m ? h("li", { class: "row" },
    h("span", { class: "faint", text: e.at }), m.marker ? null : h("strong", { text: displayName(m.actor || e.actor) }), h("span", null, linkify(m.marker || m.text))) : null; }))));
  body.push(h("details", { class: "section", "data-k": "change-" + d.id }, h("summary", null, icon("chevron", "sm"), "Change this task"), taskControls(st, d, builders)));
  return { title: d.title, body };
};

function acceptForm(d, builders) {
  const files = h("input", { type: "text", id: "acc-files-" + d.id, "data-k": "acc-files-" + d.id, value: d.files.join(", "), spellcheck: "false", placeholder: "src/search.py, tests/test_search.py" });
  const proof = h("input", { type: "text", id: "acc-proof-" + d.id, "data-k": "acc-proof-" + d.id, value: d.proof.join(" && "), spellcheck: "false", placeholder: "python -m pytest -q tests/test_search.py" });
  const owner = h("select", { id: "acc-owner-" + d.id, "data-k": "acc-owner-" + d.id }, h("option", { value: "" }, "Whichever AI is free"), builders.map(x => h("option", { value: x.handle }, x.handle)));
  return h("div", { class: "stack" },
    h("div", { class: "field" }, h("label", { for: "acc-files-" + d.id, text: "Files it may change" }), h("span", { class: "help", text: "Separate with commas. Patterns like src/** work." }), files),
    h("div", { class: "field" }, h("label", { for: "acc-proof-" + d.id, text: "Test command" }), h("span", { class: "help", text: "Runs on your computer when the work is done, to prove it works." }), proof),
    h("div", { class: "field" }, h("label", { for: "acc-owner-" + d.id, text: "Who does it" }), owner),
    h("div", { class: "row" }, h("button", { class: "you", type: "button", onclick: e => act("task.accept",
      { task: d.id, files: csv(files.value), proof: cmds(proof.value).length ? cmds(proof.value) : null, owner: owner.value || null },
      { button: e.currentTarget, title: "Added " + d.id }) }, "Add to the work"),
    h("button", { type: "button", onclick: e => act("task.cancel", { task: d.id, reason: "not needed (decided by the human)" }, { button: e.currentTarget, title: "Set aside " + d.id, after: close }) }, "Not now")));
}

function taskControls(st, d, builders) {
  if (["done", "cancelled"].includes(d.status)) return h("p", { class: "faint", text: "Finished tasks can't be changed." });
  const reviewSel = h("select", { id: "t-check", onchange: e => act("task.set_review", { task: d.id, level: e.target.value }) },
    ["default", "low", "mid", "high"].map(v => h("option", { value: v, selected: v === "default" ? true : null }, v === "default" ? `Project default (${CHECKING[st.project.review]})` : CHECKING[v])));
  const ownerSel = h("select", { id: "t-owner", onchange: e => act("task.reassign", { task: d.id, owner: e.target.value || null }) },
    h("option", { value: "" }, "Whichever AI is free"), builders.map(x => h("option", { value: x.handle, selected: x.handle === d.owner ? true : null }, x.handle)));
  const confirmKey = "cancel-" + d.id;
  const reason = h("input", { type: "text", "data-k": "cancel-task-" + d.id, placeholder: "Why", "aria-label": "Reason for cancelling" });
  return h("div", { class: "stack" },
    h("div", { class: "field" }, h("label", { for: "t-owner", text: "Who does it" }), ownerSel),
    h("div", { class: "field" }, h("label", { for: "t-check", text: "How carefully it is checked" }), reviewSel),
    h("div", { class: "row" },
      h("button", { type: "button", onclick: () => { ui.editOpen = ui.editOpen === d.id ? false : d.id; render(); } }, "Edit details"),
      h("button", { type: "button", onclick: () => { ui.linkOpen = ui.linkOpen === d.id ? false : d.id; render(); } }, "Link to another task"),
      ui.confirm[confirmKey] ? null : h("button", { class: "danger", type: "button", onclick: () => { ui.confirm[confirmKey] = true; render(); } }, "Cancel task…")),
    ui.editOpen === d.id ? editForm(d) : null,
    ui.linkOpen === d.id ? linkForm(st, d) : null,
    ui.confirm[confirmKey] ? h("div", { class: "row" }, reason, h("button", { class: "danger", type: "button", onclick: e => {
      if (!reason.value.trim()) { toast("Add a reason", "The AI working on it reads it."); return; }
      act("task.cancel", { task: d.id, reason: reason.value.trim() }, { button: e.currentTarget, after: () => { ui.confirm[confirmKey] = false; } });
    } }, "Cancel task"), h("button", { type: "button", onclick: () => { ui.confirm[confirmKey] = false; render(); } }, "Keep it")) : null);
}

function linkForm(st, d) {
  const rel = h("select", { "aria-label": "Relation", "data-k": "link-rel" },
    [["waits_for", "waits for"], ["related", "is related to"], ["discovered_from", "was found while doing"], ["parent", "is part of group"]].map(([v, l]) => h("option", { value: v }, l)));
  const other = h("select", { "aria-label": "Other task", "data-k": "link-other" }, st.tasks.filter(t => t.id !== d.id).map(t => h("option", { value: t.id }, `${t.id} ${fit(t.title, 40)}`)));
  return h("div", { class: "row" }, h("strong", { text: d.id }), rel, other,
    h("button", { class: "go", type: "button", onclick: e => act("task.link", { task: d.id, relation: rel.value, other: other.value }, { button: e.currentTarget, after: () => { ui.linkOpen = false; } }) }, "Add link"));
}

function editForm(d) {
  const early = ["backlog", "open", "ready"].includes(d.status);
  const t = h("input", { type: "text", id: "e-title", "data-k": "e-title-" + d.id, value: d.title });
  const p = h("select", { id: "e-prio", "data-k": "e-prio-" + d.id }, [0, 1, 2, 3, 4].map(n => h("option", { value: String(n), selected: n === d.priority ? true : null }, PRIORITY[n])));
  const l = h("input", { type: "text", id: "e-labels", "data-k": "e-labels-" + d.id, value: d.labels.join(", ") });
  const f = h("input", { type: "text", id: "e-files", "data-k": "e-files-" + d.id, value: d.files.join(", "), disabled: !early });
  const c = h("input", { type: "text", id: "e-proof", "data-k": "e-proof-" + d.id, value: d.proof.join(" && "), disabled: !early });
  return h("div", { class: "stack box" },
    h("div", { class: "field" }, h("label", { for: "e-title", text: "Title" }), t),
    h("div", { class: "field" }, h("label", { for: "e-prio", text: "Priority" }), p),
    h("div", { class: "field" }, h("label", { for: "e-labels", text: "Labels" }), l),
    h("div", { class: "field" }, h("label", { for: "e-files", text: "Files" }), early ? null : h("span", { class: "help", text: "Fixed once work has started." }), f),
    h("div", { class: "field" }, h("label", { for: "e-proof", text: "Test command" }), c),
    h("div", { class: "row" }, h("button", { class: "go", type: "button", onclick: e => {
      const params = { task: d.id, title: t.value.trim(), priority: Number(p.value), labels: csv(l.value) || [] };
      if (early) { params.files = csv(f.value) || []; params.proof = cmds(c.value); }
      act("task.edit", params, { button: e.currentTarget, after: () => { ui.editOpen = false; } });
    } }, "Save changes")));
}

/* ---------------------------------------------------------------- check changes yourself */

PAGES.review = st => {
  const id = (route.sub || "").toUpperCase();
  const t = taskOf(id);
  const d = cache.diff[id];
  const title = "Check " + id + (t ? ": " + t.title : "");
  if (!d) { getJSON("/api/diff?task=" + encodeURIComponent(id)).then(x => { cache.diff[id] = x; render(); }); return { title, back: "#/task/" + id, body: h("p", { class: "muted", text: "Loading the changes…" }) }; }
  const mine = st.reviews.some(r => r.task === id);
  const pts = h("textarea", { id: "rv-points", "data-k": "rv-" + id, rows: "4", placeholder: "One point per line: what is good, what must change" });
  const lines = (d.diff || "").split("\n");
  const diff = d.diff ? h("div", { class: "diff", role: "region", "aria-label": "Changes", tabindex: "0" }, lines.map(l => h("div", {
    class: l.startsWith("diff --git") || l.startsWith("+++") || l.startsWith("---") ? "file" : l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "",
    text: l || " " }))) : note(d.note || "No changes.");
  const send = verdict => e => {
    const points = pts.value.split("\n").map(x => x.trim()).filter(Boolean);
    if (verdict === "changes" && !points.length) { toast("Say what must change", "Write at least one point; the AI works from it."); pts.focus(); return; }
    act("review.submit", { task: id, verdict, points: points.length ? points : null }, { button: e.currentTarget, after: () => { delete cache.diff[id]; close(); } });
  };
  return { title, back: "#/task/" + id, wide: true, body: [
    mine ? h("p", { class: "muted", text: "No AI from another company could check this, so it comes to you. Green lines were added, red lines removed. Approve if it does what the task says; otherwise say what must change." })
      : h("p", { class: "muted", text: "Green lines were added, red lines removed." }),
    diff,
    mine ? h("div", { class: "stack" },
      h("div", { class: "field" }, h("label", { for: "rv-points", text: "Your notes" }), h("span", { class: "help", text: "Optional when you approve." }), pts),
      h("div", { class: "row" }, h("button", { class: "you", type: "button", onclick: send("approve") }, icon("check", "sm"), "Approve the changes"),
        h("button", { type: "button", onclick: send("changes") }, "Ask for changes"))) : null] };
};

/* ---------------------------------------------------------------- one AI */

function appWord(app) { return { "codex-cli": "Codex", opencode: "opencode", "claude-code": "Claude Code" }[app] || (APP_NAMES[app] || [app])[0]; }

async function browseFolder(input, btn, then) {
  busy(btn, true);
  const res = await post("/api/do", { kind: "pick_folder" });
  busy(btn, false);
  if (!res.ok) { showResult(res); return; }
  if (!res.folder) return;
  input.value = res.folder;
  if (then) then(res.folder);
}

function startLabel(x) {
  return { terminal: "Start in a terminal", vscode: "Open in VS Code", editor: "Open in " + x.app_label.replace(" editor", "") }[x.start.kind] || "Show me how";
}
function startHint(x) {
  return { terminal: "Roundtable opens a terminal window with it, already connected.", vscode: "Roundtable opens its folder in VS Code. Then you send it one message.",
    editor: "Roundtable opens its folder in the editor. Then you send it one message." }[x.start.kind] || "You open its app yourself and send it one message.";
}

async function startSeat(x, btn) {
  if (!["terminal", "vscode", "editor"].includes(x.start.kind)) { ui.started[x.handle] = { steps: x.start.steps, join: x.start.join }; render(); return; }
  const res = await special("start", { handle: x.handle }, { button: btn, silent: true });
  if (res.ok) { ui.started[x.handle] = { text: res.text, join: res.join, steps: res.steps, kind: x.start.kind }; toast(capital(plainText(res.text)), x.start.kind === "terminal" ? "Allow the Roundtable tools when the app asks." : "Then send the message shown here."); }
  else { ui.started[x.handle] = { error: res.message, hint: res.hint, command: res.command, folder: res.folder, join: x.start.join, steps: x.start.steps }; toast(capital(plainText(res.message)) || "Could not start it", "Run the command shown under its name instead.", { error: true }); }
  render();
}

function startedBox(x, info) {
  return h("div", { class: "stack tight" },
    info.error ? h("p", null, h("strong", { text: plainText(info.error) })) : null,
    info.command ? [h("p", { class: "faint", text: "Run this in a terminal instead:" }), copyBox(`cd ${info.folder || ""} && ${info.command}`.replace(/^cd  && /, ""))] : null,
    info.kind === "terminal" && !info.error ? h("p", { class: "faint", text: "A terminal window opened. Allow the Roundtable tools when it asks; it joins by itself." }) : null,
    info.steps && info.steps.length && info.kind !== "terminal" ? h("ol", { class: "stack tight" }, info.steps.map(t => h("li", { text: t }))) : null,
    info.join && info.kind !== "terminal" ? [h("p", { class: "faint", text: "Then send this message in its chat:" }), copyBox(info.join)] : null);
}

function meter(label, pct, sub, warnAt) {
  if (pct === null || pct === undefined) return null;
  const v = Math.max(0, Math.min(100, Number(pct)));
  const fill = h("div", { class: "fill" + (v >= warnAt ? " stop" : v >= warnAt * 0.75 ? " warn" : "") });
  fill.style.width = v + "%";
  return h("div", { class: "meter", title: sub || null }, h("span", { text: label }),
    h("div", { class: "track", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(v)), "aria-label": label }, fill),
    h("span", { class: "val", text: Math.round(v) + "%" }));
}

function resets(epoch) {
  if (!epoch) return "";
  const mins = Math.round((Number(epoch) * 1000 - Date.now()) / 60000);
  if (mins <= 0) return "resetting now";
  return mins < 90 ? `resets in ${mins} min` : mins < 2880 ? `resets in ${Math.round(mins / 60)} h` : `resets in ${Math.round(mins / 1440)} days`;
}

function usageBlock(x, warnAt) {
  const u = x.usage, snap = u.snapshot || {}, ex = u.exchange;
  const reset = w => w && w.reset ? h("div", { class: "meter" }, h("span", { text: w === snap.limit_5h ? "5 hours" : "Week" }),
    h("span", { class: "faint", text: `Reset since${w.was != null ? ` (it was ${Math.round(w.was)}%)` : ""}; new numbers come with its next reply` }), h("span")) : null;
  const meters = u.snapshot ? [
    meter("Chat", snap.context_pct, snap.context_size ? `of ${Math.round(snap.context_size / 1000)}k tokens` : "", warnAt),
    reset(snap.limit_5h) || meter("5 hours", snap.limit_5h && snap.limit_5h.pct, snap.limit_5h && resets(snap.limit_5h.resets_at), warnAt),
    reset(snap.limit_7d) || meter("Week", snap.limit_7d && snap.limit_7d.pct, snap.limit_7d && resets(snap.limit_7d.resets_at), warnAt)].filter(Boolean) : [];
  return h("div", { class: "stack tight" },
    meters.length ? h("div", null, meters) : h("p", { class: "muted", text: ["claude-code", "codex-cli", "codex-vscode", "codex-app"].includes(x.app)
      ? "No numbers yet. They appear after its first reply" + (x.app === "claude-code" ? " when it is started from Roundtable." : ".")
      : "This app doesn't share how much it has used." }),
    snap.updated_at ? h("p", { class: ago(snap.updated_at) > 1800 ? "box warn" : "faint", text: `Numbers from ${agoText(snap.updated_at)}` +
      (ago(snap.updated_at) > 1800 ? ". They only update while it works, so they may be out of date." : ".") }) : null,
    h("dl", { class: "kv" },
      snap.session_tokens ? [h("dt", { text: "This chat" }), h("dd", { text: num(snap.session_tokens) + " tokens" })] : null,
      snap.limit_5h && !snap.limit_5h.reset ? [h("dt", { text: "5-hour limit" }), h("dd", { text: resets(snap.limit_5h.resets_at) || "-" })] : null,
      snap.limit_7d && !snap.limit_7d.reset ? [h("dt", { text: "Weekly limit" }), h("dd", { text: resets(snap.limit_7d.resets_at) || "-" })] : null,
      x.runner && x.runner.tokens ? [h("dt", { text: "Background runs" }), h("dd", { text: `about ${num(x.runner.tokens)} tokens in ${plural(x.runner.runs || 0, "run")}` })] : null,
      h("dt", { text: "Roundtable" }), h("dd", { text: `${num(ex.calls)} messages, about ${num(ex.tokens)} tokens (${num(ex.tokens_today)} today)` })));
}

const EFFORT_LABEL = { minimal: "Minimal", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Max", ultra: "Ultra" };

PAGES.ai = st => {
  const x = seatOf(route.sub);
  if (!x) return { title: "Not found", body: h("p", { class: "muted", text: "There is no AI called " + route.sub + "." }) };
  const info = ui.started[x.handle];
  const warn = (st.config.find(c => c.key === "usage.warn_percent") || { value: 90 }).value;
  const jobs = ["plan", "build", "review"].filter(r => x.roles.includes(r)).map(r => ({ plan: "writes plans", build: "builds", review: "checks others' work" }[r]));
  const rmKey = "rm-" + x.handle;
  const startBtn = x.status !== "active" ? null : h("button", { class: needsStart(x) && !x.can_run ? "go" : "", type: "button", onclick: e => startSeat(x, e.currentTarget) },
    icon(x.start.kind === "terminal" ? "terminal" : x.start.kind === "desktop" ? "desktop" : "code", "sm"), (x.active || x.live) && x.start.kind === "terminal" ? "Open another terminal" : startLabel(x));
  const act_ = cache.activity[x.handle];
  return { title: x.handle, wide: true, body: [
    h("div", { class: "row" }, avatar(x.handle, "lg"), h("div", null, h("strong", { text: prettyModel(x.model) + (x.effort ? ` · ${EFFORT_LABEL[x.effort] || x.effort} thinking` : "") }), h("p", { class: "muted", text: x.app_label })),
      h("span", { class: "pill " + (x.status === "paused" ? "" : lampOf(x) === "busy" ? "work" : lampOf(x) === "on" ? "ok" : "you"), text: seatPhrase(x) })),
    x.can_run ? runnerSection(x) : null,
    sec("What it is doing", liveList(x, act_)),
    sec(x.can_run ? "Or open it yourself" : "Start it", h("p", { class: "muted", text: startHint(x) }), h("div", { class: "row" }, startBtn), info ? startedBox(x, info) : null,
      !info && x.start.kind !== "terminal" ? [x.start.steps && x.start.steps.length ? h("ol", { class: "stack tight" }, x.start.steps.map(t => h("li", { text: t }))) : null,
        x.start.join ? [h("p", { class: "faint", text: "The message to send in its chat:" }), copyBox(x.start.join)] : null] : null,
      h("p", { class: "faint", text: "An AI you open yourself only acts while you talk to it: if its chat goes quiet, type “check roundtable” in it." })),
    sec("Model and thinking", modelForm(x)),
    sec("What it does", h("p", { text: capital(listWords(jobs)) + "." + (x.roles.includes("build") ? "" : " It can't edit files.") }),
      x.tasks.length ? h("ul", { class: "tasklist" }, x.tasks.map(id => taskOf(id)).filter(Boolean).map(taskButton)) : null,
      x.worktree ? h("p", { class: "faint" }, "Works in its own copy of your project: ", h("span", { class: "mono", text: x.worktree })) : null),
    sec("Usage", usageBlock(x, warn)),
    sec("More", h("div", { class: "row" },
      x.status === "paused" ? h("button", { type: "button", onclick: e => act("seat.resume", { handle: x.handle }, { button: e.currentTarget }) }, icon("play", "sm"), "Resume")
        : h("button", { type: "button", onclick: e => act("seat.pause", { handle: x.handle }, { button: e.currentTarget }) }, icon("pause", "sm"), "Pause"),
      x.live ? h("button", { type: "button", title: "Use this if you closed its chat and want to start it again", onclick: e => act("seat.release", { handle: x.handle }, { button: e.currentTarget }) }, "Forget its old chat") : null,
      x.worktree ? h("button", { type: "button", onclick: e => special("folder", { path: x.worktree }, { button: e.currentTarget }) }, icon("folder", "sm"), "Open its folder") : null,
      ui.confirm[rmKey]
        ? h("button", { class: "danger", type: "button", onclick: e => act("seat.remove", { handle: x.handle }, { button: e.currentTarget, after: () => { ui.confirm[rmKey] = false; close(); } }) }, "Yes, remove " + x.handle)
        : h("button", { class: "ghost danger", type: "button", onclick: () => { ui.confirm[rmKey] = true; render(); setTimeout(() => { ui.confirm[rmKey] = false; render(); }, 5000); } }, "Remove…")))] };
};

function runnerSection(x) {
  const r = x.runner || {};
  const on = running(x);
  const state = !on ? "Not running in the background" : { working: "Working now", waiting: "Waiting for work", stuck: "Stuck", paused: "Paused", starting: "Starting" }[r.state] || "Running";
  const everything = (S.config.find(c => c.key === "runner.permissions") || {}).value === "all";
  return h("section", { class: "section runner" + (on ? " on" : "") },
    h("div", { class: "spread" }, h("h2", { text: "Run it in the background" }), h("span", { class: "pill " + (on ? (r.state === "stuck" ? "you" : r.state === "working" ? "work" : "ok") : ""), text: state })),
    h("p", { class: "muted", text: on
      ? "Roundtable starts " + x.handle + " by itself whenever it has work, with your own login, and puts it back to sleep when it is done. You don't need a terminal open."
      : "Let Roundtable start " + x.handle + " by itself whenever it has work, with your own " + appWord(x.app) + (x.app === "opencode" ? " setup (free models need no login)" : " login") + ". Nothing gets stuck waiting for you to nudge it." }),
    on && r.message ? h("p", { class: r.state === "stuck" ? "box warn" : "faint", text: capital(plainText(r.message)) + (r.runs ? ` · ${plural(r.runs, "run")} so far` : "") }) : null,
    !on && r.error ? h("p", { class: "box warn", text: "Last time: " + plainText(r.error) }) : null,
    h("div", { class: "row" }, on
      ? h("button", { type: "button", onclick: e => special("stop", { handle: x.handle }, { button: e.currentTarget, title: x.handle + " stopped" }) }, icon("pause", "sm"), "Stop running in the background")
      : h("button", { class: "go", type: "button", disabled: x.status !== "active" ? true : null, onclick: e => runSeats([x.handle], e.currentTarget) }, icon("play", "sm"), "Run in the background")),
    h("p", { class: "faint" }, everything ? "It may run any command in its own copy of the project. " : "It may edit files in its own copy of the project, use git and run the project's test commands; other commands are refused. ",
      h("a", { href: "#/settings", text: "Change this in Settings" }), "."));
}

const STEP_LABEL = { think: "Thinking", say: "Said", run: "Ran", edit: "Edited", read: "Read", tool: "Roundtable", done: "Finished", error: "Problem", start: "Started" };

function liveList(x, data) {
  if (!data) return h("p", { class: "muted", text: "Loading…" });
  if (!data.items || !data.items.length) return h("p", { class: "muted", text: running(x) || x.can_run
    ? "Nothing yet. When it works, its thinking, commands and edits show up here as they happen."
    : "This app doesn't share what it is doing. Open it to watch." });
  const items = data.items.slice().reverse();
  return h("div", { class: "stack tight" },
    h("p", { class: "faint", text: `From ${data.source}${data.stale ? ", a while ago" : ""}. Newest first.` }),
    h("ol", { class: "steps-live plain" }, items.map((it, i) => h("li", { class: "step-" + it.kind },
      h("span", { class: "k" }, icon((STEP[it.kind] || [0, "dot"])[1], "sm"), STEP_LABEL[it.kind] || it.kind),
      h("div", { class: "v" }, it.kind === "run" || it.kind === "edit" || it.kind === "read" ? h("code", { text: it.text }) : longText(it.text, `act-${x.handle}-${it.t}-${i}`, "pre", 280),
        h("span", { class: "faint", text: agoText(it.t) }))))));
}

function modelForm(x) {
  const key = "ai-model-" + x.handle;
  const field = modelField(key, x.app, x.model);
  const applies = x.can_run ? "Background runs use it from their next start; a terminal you opened needs a restart." : "Takes effect the next time it starts.";
  const info = modelInfo(x.app, x.model);
  const efforts = info && info.efforts && info.efforts.length && x.efforts.length ? info.efforts.filter(v => x.efforts.includes(v)) : x.efforts;
  const save = btn => { const el = APP.querySelector("#" + CSS.escape(key)); const v = el ? el.value.trim() : ""; if (!v || v === x.model) { toast("Pick another model first", "Choose one from the list or type its name."); return; }
    act("seat.set", { handle: x.handle, model: v }, { button: btn, title: "Model changed", body: applies }); };
  return h("div", { class: "stack" },
    h("div", { class: "field" }, h("label", { for: key, text: "Model" }),
      h("div", { class: "row model-row" }, h("div", { class: "grow" }, field), h("button", { type: "button", onclick: e => save(e.currentTarget) }, "Save")),
      info ? h("span", { class: "help", text: [info.name, info.free ? "free" : "", info.context ? ctxSize(info.context) + " context" : "", info.note && info.note !== "free" ? info.note : ""].filter(Boolean).join(" · ") }) : null),
    efforts.length ? h("div", { class: "field" }, h("span", { class: "lbl-like", text: "How hard it thinks" }),
      h("span", { class: "help", text: "More thinking is slower and uses more of your limits, but catches more on hard problems." }),
      h("div", { class: "seg wrap", role: "group", "aria-label": "How hard it thinks" },
        [""].concat(efforts).map(v => h("button", { type: "button", "aria-pressed": String((x.effort || "") === v),
          onclick: e => act("seat.set", { handle: x.handle, effort: v || "default" }, { button: e.currentTarget, title: v ? `${x.handle}: ${EFFORT_LABEL[v] || v} thinking` : `${x.handle}: the app's default thinking`, body: applies }) },
          v ? EFFORT_LABEL[v] || v : "App default"))))
      : h("p", { class: "faint", text: "Set how hard it thinks in " + x.app_label + " itself." }),
    h("p", { class: "faint", text: applies }));
}

/* ---------------------------------------------------------------- choosing a model */

function loadModels(app, refresh) {
  if (!app || (cache.models[app] && !refresh)) return;
  cache.models[app] = { loading: true, models: [] };
  getJSON("/api/models?app=" + encodeURIComponent(app) + (refresh ? "&refresh=1" : ""))
    .then(r => { cache.models[app] = r && r.models ? r : { models: [] }; render(); })
    .catch(() => { cache.models[app] = { models: [] }; render(); });
}
function modelsOf(app) { return (cache.models[app] || {}).models || []; }
function modelInfo(app, id) { return modelsOf(app).find(m => m.id === id) || null; }
function ctxSize(n) { return !n ? "" : n >= 1e6 ? Math.round(n / 1e5) / 10 + "M" : Math.round(n / 1000) + "k"; }

/* A text box that takes any model name, with the app's own list underneath: search, free models marked. */
function modelField(key, app, value, cls) {
  loadModels(app);
  const data = cache.models[app] || { loading: true, models: [] };
  const open = ui.modelOpen === key;
  const input = h("input", { type: "text", id: key, "data-k": key, "data-def": value || "", class: "model-input" + (cls ? " " + cls : ""), value: value || "", spellcheck: "false", autocomplete: "off",
    onclick: () => { if (ui.modelOpen !== key) { ui.modelOpen = key; render(); } },
    role: "combobox", "aria-expanded": String(open), "aria-controls": key + "-list", placeholder: data.models.length ? "Search or type a model name" : "model name",
    onfocus: () => { if (ui.modelOpen !== key) { ui.modelOpen = key; render(); } },
    oninput: () => fill(),
    onkeydown: e => {
      if (e.key === "Escape") { ui.modelOpen = null; render(); }
      if (e.key === "ArrowDown") { const b = listEl.querySelector("button.mi"); if (b) { e.preventDefault(); b.focus(); } }
      if (e.key === "Enter") { e.preventDefault(); ui.modelOpen = null; render(); }
    } });
  const listEl = h("div", { class: "model-list", id: key + "-list", role: "listbox", onmousedown: e => e.preventDefault() });
  const free = data.models.filter(m => m.free).length;
  function fill() {
    const q = input.value.trim().toLowerCase();
    const exact = data.models.some(m => m.id.toLowerCase() === q);
    const list = data.models.filter(m => (!ui.freeOnly || m.free) && (!q || exact || m.id.toLowerCase().includes(q) || String(m.name).toLowerCase().includes(q)));
    listEl.replaceChildren(...[
      free ? h("div", { class: "ml-bar" }, h("label", { class: "check small-check" },
        h("input", { type: "checkbox", checked: ui.freeOnly, onchange: e => { ui.freeOnly = e.target.checked; fill(); } }), h("span", { text: `Free only (${free})` })),
        h("button", { class: "ghost small", type: "button", title: "Ask the app for its newest list", onclick: () => loadModels(app, true) }, "Refresh")) : null,
      data.loading ? h("p", { class: "faint ml-empty", text: "Loading the app's models…" })
        : !list.length ? h("p", { class: "faint ml-empty", text: data.models.length ? "No model matches. You can still use the name you typed." : "This app doesn't share a list. Type the model name it uses." })
          : list.slice(0, 200).map(m => h("button", { type: "button", class: "mi", role: "option", "aria-selected": String(m.id === input.value),
            onclick: () => { input.value = m.id; ui.modelOpen = null; input.dispatchEvent(new Event("change")); render(); },
            onkeydown: e => { if (e.key === "ArrowDown" && e.target.nextElementSibling) { e.preventDefault(); e.target.nextElementSibling.focus(); }
              if (e.key === "ArrowUp") { e.preventDefault(); (e.target.previousElementSibling && e.target.previousElementSibling.classList.contains("mi") ? e.target.previousElementSibling : input).focus(); }
              if (e.key === "Escape") { ui.modelOpen = null; render(); } } },
            h("span", { class: "mi-main" }, h("strong", { text: m.name }), h("code", { text: m.id })),
            h("span", { class: "mi-tags" }, m.free ? h("span", { class: "pill ok", text: "Free" }) : null,
              m.context ? h("span", { class: "pill", text: ctxSize(m.context) + " context" }) : null),
            m.note && m.note !== "free" ? h("span", { class: "mi-note", text: fit(m.note, 90) }) : null))].flat().filter(Boolean));
  }
  fill();
  requestAnimationFrame(() => {
    if (ui.modelOpen !== key) return;
    fill();
    const r = input.getBoundingClientRect();
    listEl.classList.toggle("up", r.bottom + 350 > window.innerHeight && r.top > 360);
  });
  return h("div", { class: "model-field" + (open ? " open" : "") }, input, open ? listEl : null);
}

document.addEventListener("mousedown", e => {
  if (ui.modelOpen && !(e.target.closest && e.target.closest(".model-field"))) { ui.modelOpen = null; render(); }
});

/* ---------------------------------------------------------------- add AIs: pick apps, then names */

function suggestName(taken, app, model) {
  const skip = ["claude", "gpt", "gemini", "qwen", "models", "model", "code", "cli", "opencode", "free", "preview", "flash"];
  const fromModel = String(model || "").toLowerCase().split("/").pop().split(/[-_. ]+/).find(x => /^[a-z]{2,}$/.test(x) && !skip.includes(x));
  const base = fromModel || { "gemini-cli": "gemini", "qwen-code": "qwen", opencode: "opencode", "copilot-cli": "copilot", cursor: "cursor", "codex-cli": "codex", "codex-vscode": "codex", "codex-app": "codex" }[app.key] || "helper";
  let name = base, i = 2;
  while (taken.has(name)) name = base + i++;
  taken.add(name);
  return name;
}

function picker(st, onDone) {
  const groups = APP_GROUPS.map(([g, label, ic, help]) => {
    const list = st.apps.filter(a => groupOf(a) === g);
    if (!list.length) return null;
    return h("div", { class: "stack tight" }, h("p", { class: "group-title" }, label, h("span", { class: "faint", text: " · " + help })),
      h("div", { class: "tiles" }, list.map(a => {
        const [name, sub] = APP_NAMES[a.key] || [a.label, ""];
        const on = !!ui.pick[a.key];
        return h("button", { class: "tile", type: "button", "aria-pressed": String(on), onclick: () => { if (on) delete ui.pick[a.key]; else ui.pick[a.key] = true; render(); } },
          h("span", { class: "row" }, h("span", { class: "av sm", "data-c": a.company || "other", "aria-hidden": "true", text: monogram(name) }),
            h("span", { class: "check-mark", "aria-hidden": "true" }, on ? icon("check", "sm") : null)),
          h("strong", { text: name }), h("span", { text: sub }),
          SUGGESTED.includes(a.key) ? h("span", { class: "pill ok", text: "Popular" }) : null);
      })));
  });
  const picked = st.apps.filter(a => ui.pick[a.key]);
  const taken = new Set(st.seats.map(x => x.handle));
  const rows = picked.map(a => {
    const [name] = APP_NAMES[a.key] || [a.label];
    loadModels(a.key);
    const known = modelsOf(a.key);
    const suggestions = a.company ? (st.models[a.company] || []) : [];
    const defModel = (known[0] && (a.key === "opencode" ? (known.find(m => m.free) || known[0]).id : known[0].id)) || (a.company && suggestions[0] ? suggestions[0] : "");
    return { a, el: h("div", { class: "joinrow" }, h("span", { class: "av", "data-c": a.company || "other", "aria-hidden": "true", text: monogram(name) }),
      h("div", { class: "who" }, h("strong", { text: name }), h("p", { class: "faint", text: (APP_NAMES[a.key] || ["", ""])[1] })),
      h("div", { class: "field" }, h("label", { for: "pk-name-" + a.key, text: "Its name" }),
        h("input", { type: "text", id: "pk-name-" + a.key, "data-k": "pk-name-" + a.key, class: "pk-name", maxlength: "24", autocomplete: "off", spellcheck: "false", value: suggestName(taken, a, defModel) })),
      h("div", { class: "field" }, h("label", { for: "pk-model-" + a.key, text: "Model" }), modelField("pk-model-" + a.key, a.key, defModel, "pk-model"),
        a.key === "opencode" ? h("span", { class: "help", text: "Free models need no account. Paid ones use the providers you signed in to in opencode." }) : null)) };
  });
  const add = async btn => {
    const list = rows.map(r => ({ a: r.a, handle: r.el.querySelector(".pk-name").value.trim().toLowerCase(), model: r.el.querySelector(".pk-model").value.trim() }));
    for (const x of list) {
      if (!/^[a-z][a-z0-9_-]{1,23}$/.test(x.handle)) { toast("Pick another name for " + (APP_NAMES[x.a.key] || [x.a.label])[0], "2 to 24 letters, digits, - or _, starting with a letter. For example opus or sol."); return; }
      if (!x.model) { toast("Which model for " + (APP_NAMES[x.a.key] || [x.a.label])[0] + "?", "Type the model name the app uses."); return; }
    }
    if (new Set(list.map(x => x.handle)).size < list.length) { toast("Two AIs have the same name", "Give each one its own name."); return; }
    busy(btn, true);
    const added = [];
    for (const x of list) {
      const res = await post("/api/action", { op: "seat.add", params: { handle: x.handle, model: x.model, app: x.a.key } });
      if (!res.ok) { showResult(res); break; }
      added.push(x.handle);
      delete ui.pick[x.a.key];
    }
    busy(btn, false);
    if (added.length) toast(`Added ${listWords(added)}`, "Next, start them.");
    await refresh(true);
    if (added.length && onDone) onDone(added);
  };
  return h("div", { class: "stack" }, groups,
    picked.length ? h("section", { class: "section", "aria-label": "Names and models" }, h("h2", { text: "Name them" }),
      h("p", { class: "muted", text: "Short lowercase names. The AIs use them to talk to each other. The model is filled in; change it if you use another." }),
      rows.map(r => r.el)) : null,
    picked.length ? h("div", { class: "pickbar", role: "region", "aria-label": "Chosen apps" },
      h("span", null, h("strong", { text: plural(picked.length, "AI") + " chosen" }), h("span", { text: ": " + listWords(picked.map(a => (APP_NAMES[a.key] || [a.label])[0])) })),
      h("button", { class: "you", type: "button", onclick: e => add(e.currentTarget) }, icon("plus", "sm"), picked.length === 1 ? "Add this AI" : `Add these ${picked.length} AIs`)) : null);
}

PAGES.add = st => ({ title: "Add an AI", wide: true, body: [
  h("p", { class: "muted", text: "Pick the apps your AIs run in. Each uses your own subscription; no API keys. Two from different companies catch each other's mistakes." }),
  picker(st, added => go("#/ai/" + added[0]))] });

/* ---------------------------------------------------------------- the team, and everything else on small screens */

PAGES.team = st => ({ title: "Your team", body: [
  st.seats.length ? h("ul", { class: "list" }, st.seats.map(x => h("li", { class: "row" }, avatar(x.handle),
    h("div", { class: "grow" }, h("strong", { text: x.handle }), " ", h("span", { class: "faint", text: `${prettyModel(x.model)} · ${x.app_label}` }), h("p", { class: needsStart(x) ? "you-text" : "muted", text: seatPhrase(x) })),
    needsStart(x) ? h("button", { class: "go small", type: "button", onclick: e => startSeat(x, e.currentTarget) }, startLabel(x)) : null,
    h("button", { class: "small", type: "button", onclick: () => go("#/ai/" + x.handle) }, "Open"))))
    : h("p", { class: "muted", text: "Nobody yet. Add two or more AIs, ideally from different companies." }),
  h("div", { class: "row" }, h("button", { class: "go", type: "button", onclick: () => go("#/add") }, icon("plus", "sm"), "Add an AI"), pauseButton(true)),
  h("details", { class: "section", "data-k": "connect" }, h("summary", null, icon("chevron", "sm"), "Connect apps you open yourself"), connectPanel(st)),
  sec("More", h("ul", { class: "tasklist" }, [["plan", "plan", "The plan"], ["alerts", "alert", "Problems and votes"], ["usage", "usage", "Usage and limits"], ["notes", "notes", "Notes for the AIs"],
    ["history", "history", "Everything that happened"], ["settings", "settings", "Settings"], ["help", "help", "Help"], ["switch", "folder", "Open another project"]].map(([r, ic, label]) =>
    h("li", null, h("button", { type: "button", onclick: () => go("#/" + r) }, icon(ic, "sm"), h("span", { class: "t" }, h("strong", { text: label })), icon("chevron", "sm"))))),
    h("div", { class: "row" }, themeButton(true), h("span", { class: "faint", text: "Roundtable v" + st.project.version })))] });

function connectPanel(st) {
  const c = st.project.connected;
  const items = [
    ["claude-code", "Claude Code (project settings)", "Only needed if you open Claude Code yourself instead of using Start. Writes .mcp.json in the project folder."],
    ["claude-app", "Claude desktop app", "Lets a Claude desktop chat join. Restart the app afterwards."],
    ["codex", "Codex: terminal, VS Code and the ChatGPT app", "One entry in ~/.codex/config.toml serves all three. Restart them afterwards."],
    ["copilot", "GitHub Copilot CLI", "Adds Roundtable to ~/.copilot/mcp-config.json."],
  ];
  return h("div", { class: "stack" }, h("p", { class: "muted", text: "AIs you start from here are connected automatically. These are for apps you open yourself. Roundtable adds its entry to each settings file and keeps a backup." }),
    h("ul", { class: "list" }, items.map(([key, label, help]) => h("li", { class: "stack tight" },
      h("div", { class: "row" }, h("strong", { text: label }), h("span", { class: "pill " + (c[key] ? "ok" : ""), text: c[key] ? "connected" : "not connected" })),
      h("p", { class: "faint", text: help }),
      ui.preview[key] ? h("div", { class: "output", text: ui.preview[key] }) : null,
      h("div", { class: "row" },
        h("button", { class: "small", type: "button", onclick: async e => { const r = await special("connect", { app: key, preview: true }, { button: e.currentTarget, silent: true }); ui.preview[key] = r.ok ? r.text : (r.message + (r.hint ? "\n" + r.hint : "")); render(); } }, "Preview the change"),
        h("button", { class: "small" + (c[key] ? "" : " go"), type: "button", onclick: e => special("connect", { app: key }, { button: e.currentTarget, title: "Connected", after: () => { delete ui.preview[key]; } }) }, c[key] ? "Update" : "Connect"),
        c[key] ? h("button", { class: "small ghost", type: "button", onclick: e => special("connect", { app: key, remove: true }, { button: e.currentTarget, title: "Disconnected" }) }, "Disconnect") : null)))));
}

/* ---------------------------------------------------------------- problems and votes */

PAGES.alerts = st => {
  const lvl = h("select", { id: "al-level", "data-k": "al-level" }, LEVELS.map(([n, name]) => h("option", { value: String(n), selected: n === 3 ? true : null }, `${n}. ${name}`)));
  const lvlHelp = h("span", { class: "help", text: LEVELS[2][2] });
  lvl.addEventListener("change", () => { lvlHelp.textContent = LEVELS[Number(lvl.value) - 1][2]; });
  const title = h("input", { type: "text", id: "al-title", "data-k": "al-title" });
  const desc = h("textarea", { id: "al-desc", "data-k": "al-desc", rows: "3" });
  const files = h("input", { type: "text", id: "al-files", "data-k": "al-files", placeholder: "src/auth/**", spellcheck: "false" });
  return { title: "Problems and votes", body: [
    st.alerts.length ? sec(null, h("ul", { class: "list" }, st.alerts.map(alertRow))) : note("No open problems.", "ok"),
    st.votes.length ? sec("Votes", h("ul", { class: "list" }, st.votes.map(voteRow))) : null,
    h("details", { class: "section", "data-k": "raise" }, h("summary", null, icon("chevron", "sm"), "Tell your AIs about a problem"),
      h("div", { class: "stack" },
        h("div", { class: "field" }, h("label", { for: "al-title", text: "What is wrong" }), title),
        h("div", { class: "field" }, h("label", { for: "al-desc", text: "Details" }), desc),
        h("div", { class: "field" }, h("label", { for: "al-level", text: "How serious" }), lvl, lvlHelp),
        h("div", { class: "field" }, h("label", { for: "al-files", text: "Files it affects (optional)" }), files),
        h("div", { class: "row" }, h("button", { class: "go", type: "button", onclick: e => {
          if (!title.value.trim()) { toast("Say what is wrong", ""); title.focus(); return; }
          act("alert.raise", { level: Number(lvl.value), title: title.value.trim(), description: desc.value.trim() || null, files: files.value.trim() || null },
            { button: e.currentTarget, title: "Your AIs have been told", after: () => { title.value = ""; desc.value = ""; files.value = ""; } });
        } }, "Tell the AIs"))))] };
};

function alertRow(a) {
  const lv = LEVELS[a.level - 1] || LEVELS[2];
  const fix = h("input", { type: "text", "data-k": "fix-" + a.id, placeholder: "What fixed it (optional)", "aria-label": "What fixed it" });
  const lvlSel = h("select", { "aria-label": "How serious", onchange: e => act("alert.set_level", { id: a.id, level: Number(e.target.value) }) },
    LEVELS.map(([n, name]) => h("option", { value: String(n), selected: n === a.level ? true : null }, `${n}. ${name}`)));
  return h("li", { class: "stack tight" },
    h("div", { class: "row" }, avatar(a.by, "sm", true), h("span", { class: "pill " + (a.level >= 4 ? "stop" : a.level === 3 ? "you" : ""), text: lv[1] }), h("strong", { text: a.title })),
    h("p", { class: "faint", text: `${a.id}, reported by ${who(a.by)} ${a.at}. ${lv[2]}` + (a.must_ack.length ? ` Acknowledged by ${listWords(a.acked) || "nobody yet"} of ${listWords(a.must_ack)}.` : "") }),
    a.description ? h("p", { class: "pre", text: a.description }) : null,
    a.proposed ? h("p", { class: "box warn" }, `${a.proposed_by} thinks this is level ${a.proposed} (${LEVELS[a.proposed - 1][1]}). `,
      h("button", { class: "small", type: "button", onclick: e => act("alert.set_level", { id: a.id, level: a.proposed }, { button: e.currentTarget }) }, `Change it to ${a.proposed}`)) : null,
    a.files.length ? h("p", { class: "faint" }, "Files: ", h("span", { class: "mono", text: a.files.join(", ") })) : null,
    a.evidence ? h("details", { "data-k": "ev-" + a.id }, h("summary", null, icon("chevron", "sm"), "Evidence"), h("div", { class: "output", text: a.evidence })) : null,
    h("div", { class: "row" }, h("div", { class: "grow" }, fix), h("button", { class: "you small", type: "button", onclick: e => act("alert.resolve", { id: a.id, resolution: fix.value.trim() || "solved by the human" }, { button: e.currentTarget, title: "Marked as solved" }) }, "Mark as solved"), lvlSel));
}

function voteRow(v) {
  const tied = v.status === "tied";
  return h("li", { class: "stack tight" }, h("strong", { text: v.topic }),
    h("p", { class: "faint", text: tied ? "The AIs are split evenly. You decide." : `The AIs are voting (${v.ballots.length} of ${v.voters.length} in). You can decide now if you want.` }),
    h("ul", { class: "plain stack tight" }, v.options.map(o => {
      const bs = v.ballots.filter(b => b.choice === o);
      return h("li", { class: "box stack tight" }, h("div", { class: "row" }, h("strong", { text: o }), h("span", { class: "faint", text: plural(bs.length, "vote") }),
        h("button", { class: (tied ? "you " : "") + "small", type: "button", onclick: e => act("vote.decide", { id: v.id, choice: o }, { button: e.currentTarget, title: "Decided" }) }, "Choose this")),
        bs.map(b => h("p", { class: "muted", text: `${b.seat}: ${b.reason}` })));
    })));
}

/* ---------------------------------------------------------------- work the AIs found */

PAGES.found = st => {
  const list = st.tasks.filter(t => t.status === "backlog");
  const builders = st.seats.filter(x => x.roles.includes("build") && x.status === "active");
  return { title: "Work your AIs found", body: [
    h("p", { class: "muted", text: "While working, your AIs write down other things that need doing. Nothing here starts until you add it to the work." }),
    list.length ? h("ul", { class: "list" }, list.map(t => h("li", { class: "stack tight" },
      h("div", { class: "row" }, avatar(t.filed_by || "human", "sm", true), h("strong", { text: t.title }), h("a", { class: "tid", href: "#/task/" + t.id, text: t.id })),
      t.summary ? h("p", { class: "muted pre", text: plainText(t.summary) }) : null,
      ui.accepting[t.id] || !(t.kind === "epic" || (t.files.length && t.proof.length)) ? h("details", { "data-k": "acc-" + t.id, open: ui.accepting[t.id] ? true : null },
        h("summary", null, icon("chevron", "sm"), "Add to the work…"), acceptForm(t, builders))
        : h("div", { class: "row" }, h("button", { class: "you small", type: "button", onclick: e => act("task.accept", { task: t.id }, { button: e.currentTarget, title: "Added " + t.id }) }, "Add to the work"),
          h("button", { class: "small", type: "button", onclick: e => act("task.cancel", { task: t.id, reason: "not needed (decided by the human)" }, { button: e.currentTarget, title: "Set aside " + t.id }) }, "Not now")))))
      : note("Nothing waiting. New finds show up above the message box.", "ok")] };
};

/* ---------------------------------------------------------------- usage */

PAGES.usage = st => {
  const warn = (st.config.find(c => c.key === "usage.warn_percent") || { value: 90 }).value;
  return { title: "Usage and limits", body: [
    h("p", { class: "muted", text: "How much each AI has used, as its own app reports it." }),
    st.seats.length ? st.seats.map(x => sec(null, h("div", { class: "row" }, avatar(x.handle, "sm", true), h("strong", { text: x.handle }), h("span", { class: "faint", text: `${prettyModel(x.model)} · ${x.app_label}` })), usageBlock(x, warn)))
      : note("Add AIs to see their usage."),
    h("details", { class: "section", "data-k": "usage-src" }, h("summary", null, icon("chevron", "sm"), "Where these numbers come from"), h("div", { class: "stack tight muted" },
      h("p", { text: "Claude Code started from Roundtable reports how full its chat is, its tokens and the 5-hour and weekly limits. Codex (terminal, VS Code and ChatGPT app) writes them to its session logs, which Roundtable reads. Other apps don't share this, so only Roundtable's own messages are shown for them." }),
      h("p", { text: `Roundtable's tool descriptions cost about ${num(st.overhead_tokens)} tokens once per chat. Message tokens are estimated from characters (about 4 per token).` })))] };
};

/* ---------------------------------------------------------------- notes */

PAGES.notes = st => {
  const text = h("textarea", { id: "mem-text", "data-k": "mem-text", rows: "3", placeholder: "Tests need DATABASE_URL set; use the sqlite one in tests/.env" });
  const tags = h("input", { type: "text", id: "mem-tags", "data-k": "mem-tags", placeholder: "tests" });
  return { title: "Notes for the AIs", body: [
    h("p", { class: "muted", text: "Every AI reads these when it joins, so a new chat starts with what earlier ones learned. Notes written by AIs are shown to the others as information, never as instructions." }),
    sec("Add a note", h("div", { class: "field" }, h("label", { for: "mem-text", text: "Note (60 words at most)" }), text),
      h("div", { class: "field" }, h("label", { for: "mem-tags", text: "Tags (optional)" }), tags),
      h("div", { class: "row" }, h("button", { class: "go", type: "button", onclick: e => {
        if (!text.value.trim()) { toast("Write the note first", ""); text.focus(); return; }
        act("memory.add", { text: text.value.trim(), tags: csv(tags.value) }, { button: e.currentTarget, title: "Saved", after: () => { text.value = ""; tags.value = ""; } });
      } }, "Save note"))),
    st.memories.length ? sec(plural(st.memories.length, "note"), h("ul", { class: "list" }, st.memories.map(m => h("li", { class: "stack tight" },
      h("div", { class: "row" }, avatar(m.author, "sm", true), h("span", { class: "faint", text: `${who(m.author)}, ${m.at}` }), m.pinned ? h("span", { class: "pill you", text: "pinned" }) : null, m.tags.map(t => h("span", { class: "pill", text: t }))),
      h("p", { class: "pre", text: m.text }),
      h("div", { class: "row" },
        h("button", { class: "ghost small", type: "button", onclick: e => act("memory.pin", { id: m.id, pinned: !m.pinned }, { button: e.currentTarget }) }, m.pinned ? "Unpin" : "Pin to the top"),
        h("button", { class: "ghost small danger", type: "button", onclick: e => act("memory.forget", { id: m.id, reason: "removed from the dashboard" }, { button: e.currentTarget }) }, "Delete"))))))
      : note("No notes yet. The AIs add notes as they learn things about the project; you can too.")] };
};

/* ---------------------------------------------------------------- history */

PAGES.history = st => {
  const q = h("input", { type: "search", "data-k": "act-q", placeholder: "Search: a word, an AI's name or a task like T3", "aria-label": "Search the history" });
  const events = cache.log && cache.logKey ? cache.log : st.events;
  const run = async more => {
    const params = new URLSearchParams();
    const v = q.value.trim();
    if (/^T\d+$/i.test(v)) params.set("task", v); else if (v) params.set("q", v);
    if (more && events.length) params.set("before", events[events.length - 1].id);
    const res = await getJSON("/api/log?" + params);
    cache.log = more ? events.concat(res.events || []) : (res.events || []);
    cache.logKey = params.toString() || "all";
    render();
  };
  let day = "";
  const rows = [];
  events.forEach(e => {
    const m = say(e);
    if (!m) return;
    if (e.day !== day) { day = e.day; rows.push(h("li", { class: "day", text: dayLabel(day) })); }
    rows.push(h("li", { class: "row hist" }, h("time", { class: "faint", text: e.at }), avatar(m.marker ? "system" : m.actor || e.actor, "sm", true),
      h("span", null, m.marker ? null : h("strong", { text: displayName(m.actor || e.actor) + " " }), linkify(m.marker || m.text))));
  });
  return { title: "Everything that happened", body: [
    h("form", { class: "row", role: "search", onsubmit: e => { e.preventDefault(); run(false); } }, h("div", { class: "grow" }, q),
      h("button", { type: "submit" }, icon("search", "sm"), "Search"),
      cache.logKey ? h("button", { class: "ghost", type: "button", onclick: () => { cache.log = null; cache.logKey = ""; render(); } }, "Clear") : null),
    rows.length ? h("ul", { class: "plain stack tight" }, rows) : note("Nothing found."),
    events.length >= 80 ? h("div", { class: "row" }, h("button", { type: "button", onclick: () => run(true) }, "Show older")) : null] };
};

/* ---------------------------------------------------------------- settings */

const MAIN_SECTIONS = ["runner", "council", "review", "proof", "git", "watch", "usage", "project"];
const SECTION_LABEL = { project: "Project", review: "Checking each other's work", leases: "File locks", seats: "AIs", proof: "Tests", planning: "Planning", limits: "Limits",
  git: "Git", watch: "Notifications", usage: "Usage", dashboard: "Dashboard", history: "History", runner: "Background runs", council: "Asking the table" };
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
  "runner.permissions": ["What an AI running in the background may do", "Its own files, git and the project's test commands; or any command in its own copy of the project."],
  "runner.max_minutes": ["Stop a background run after (minutes)", "A run that goes on longer is stopped; the AI picks up again at its next run."],
  "council.rescue": ["Second opinion on failing tasks", "When a task fails its tests twice in a row, an AI from another company looks at it and tells the builder what it found."],
  "council.chair": ["Who writes the final answer", "The AI whose answer the others ranked best, or each AI in turn."],
  "council.max_minutes": ["Stop an answer after (minutes)", "Each answer, ranking or final answer."],
};
const CHOICE_TEXT = { "runner.permissions": { edits: "Its own files, git and tests", all: "Any command" }, "council.chair": { best: "The best-ranked AI", rotate: "Each AI in turn" } };

PAGES.settings = st => {
  const sections = {};
  st.config.forEach(c => (sections[c.section] = sections[c.section] || []).push(c));
  const doc = cache.doctor;
  return { title: "Settings", body: [
    h("p", { class: "muted", text: "Changes save at once. The AIs can't change these." }),
    Object.entries(sections).filter(([k]) => MAIN_SECTIONS.includes(k)).sort((a, b) => MAIN_SECTIONS.indexOf(a[0]) - MAIN_SECTIONS.indexOf(b[0]))
      .map(([k, items]) => sec(SECTION_LABEL[k] || k, items.map(settingRow))),
    h("details", { class: "section", "data-k": "more-settings" }, h("summary", null, icon("chevron", "sm"), "More: limits, planning, file locks, history"),
      h("div", { class: "stack" }, Object.entries(sections).filter(([k]) => !MAIN_SECTIONS.includes(k)).map(([k, items]) => sec(SECTION_LABEL[k] || k, items.map(settingRow))))),
    sec("Check the setup", h("p", { class: "muted", text: "Looks at git, the AIs' copies of the project, app connections and the commit guard." }),
      h("div", { class: "row" }, h("button", { class: "go", type: "button", onclick: async e => { busy(e.currentTarget, true); cache.doctor = await getJSON("/api/doctor"); busy(e.currentTarget, false); render(); } }, doc ? "Check again" : "Run the checks")),
      doc ? h("ul", { class: "list" }, doc.items.map(it => h("li", { class: "stack tight" }, h("div", { class: "row" },
        h("span", { class: "pill " + (it.status === "ok" ? "ok" : it.status === "warn" ? "you" : "stop"), text: it.status === "ok" ? "ok" : it.status === "warn" ? "check" : "problem" }), h("span", { text: it.message })),
        it.fix ? h("p", { class: "faint" }, "Fix: ", h("span", { class: "mono", text: it.fix })) : null))) : null),
    sec("Housekeeping", h("p", { class: "faint", text: "Tidying keeps each finished task's outcome and drops step-by-step detail older than the History setting." }),
      h("div", { class: "row" }, h("button", { type: "button", onclick: e => act("admin.compact", {}, { button: e.currentTarget }) }, "Tidy old history"),
        h("button", { type: "button", onclick: e => act("admin.export", {}, { button: e.currentTarget }) }, "Export a snapshot")))] };
};

function settingRow(c) {
  const id = "cfg-" + c.key.replace(".", "-");
  const save = v => act("admin.config_set", { key: c.key, value: v }, { title: "Saved" });
  const [label, desc] = SETTING_TEXT[c.key] || [capital(c.key.split(".")[1].replace(/_/g, " ")), c.desc];
  let control;
  if (c.type === "switch") control = h("input", { type: "checkbox", id, checked: c.value, onchange: e => save(e.target.checked ? "true" : "false") });
  else if (c.type === "choice") control = h("select", { id, onchange: e => save(e.target.value) }, c.choices.map(o => h("option", { value: o, selected: o === c.value ? true : null }, c.key === "review.level" ? CHECKING[o] : (CHOICE_TEXT[c.key] || {})[o] || o)));
  else if (c.type === "number") control = h("input", { type: "number", id, "data-k": id, min: "0", value: String(c.value), onchange: e => save(e.target.value) });
  else if (c.type === "list") control = h("input", { type: "text", id, "data-k": id, value: (c.value || []).join(", "), onchange: e => save(JSON.stringify(csv(e.target.value) || [])) });
  else control = h("input", { type: "text", id, "data-k": id, value: c.value, onchange: e => save(e.target.value) });
  return c.type === "switch"
    ? h("label", { class: "check", for: id }, control, h("span", null, h("strong", { text: label }), desc ? h("span", { class: "help", text: " " + desc }) : null))
    : h("div", { class: "field" }, h("label", { for: id, text: label }), desc ? h("span", { class: "help", text: desc }) : null, control);
}

/* ---------------------------------------------------------------- help */

PAGES.help = st => ({ title: "Help", body: [
  sec("This room", h("ul", { class: "stack tight" }, [
    ["The middle", "is the conversation: everything your AIs do arrives here as a message, newest at the bottom."],
    ["Above the message box", "is whatever needs you, with the buttons that settle it. When it's empty, you have nothing to do."],
    ["The message box", "gives your AIs a goal, or asks the table a question. Once they have a goal, it also sends them notes, problems or extra tasks."],
    ["The left", "is your team around the table. A green light means its app is open; blue means it's working. Click an AI to start it or see its usage."],
    ["The right", "is the plan: the steps while they plan, then every task while they build."],
  ].map(([a, b]) => h("li", null, h("strong", { text: a + " " }), b)))),
  sec("How the AIs work together", h("ol", { class: "stack tight" }, [
    "Each AI runs in its own app (Claude Code, Codex, VS Code, a desktop app) with your own subscription. No API keys.",
    "You give a goal. Each AI writes a plan without seeing the others', then comments on the others' plans without knowing who wrote which. One AI combines the best parts and the others agree.",
    "You read the plan and the test commands it will run, and approve. Nothing is built before you do.",
    "While an AI works on a task, that task's files are its alone. When it says it's done, Roundtable runs the tests itself, an AI from another company checks the changes, and the work is merged into your project.",
    "Claude Code, Codex and opencode can run in the background: Roundtable wakes them whenever there is work. Other apps act only while you talk to them: when a chat goes quiet, type “check roundtable” in it.",
  ].map(t => h("li", { text: t })))),
  sec("Ask the table", h("p", { text: "Choose “Ask the table” in the message box to ask anything: about your code, a design choice, a bug. Every AI answers on its own; then each one reads all the answers as Answer A, B, C, without names, says what is right and wrong in each, and ranks them. The AI whose answer the others ranked best writes the final answer from all of them. They can read your project but can't change it." }),
    h("p", { class: "muted", text: "When a task fails its tests twice in a row, Roundtable does something similar by itself: an AI from another company reads the failure in the builder's copy of the project and sends the builder a diagnosis, which it must answer. You can turn that off in Settings." })),
  sec("Words you may see in the AIs' chats", h("dl", { class: "kv" }, [
    ["Seat", "One AI in one app, with a short name like opus."], ["Working copy", "The AI's own folder with a copy of your project, on its own git branch."],
    ["Lease", "A task's files, locked to the AI working on it."], ["Proof", "The test command that shows a task works. Roundtable runs it."],
    ["Review depth", "How carefully they check each other: low is Light, mid Standard, high Thorough."], ["Lock", "Approving the plan."],
    ["Backlog", "Work an AI found, waiting for your OK."], ["Epic", "A group of tasks."], ["Memory", "The notes every AI reads."],
    ["Alert levels", "1 note, 2 heads-up, 3 must be acknowledged, 4 holds the files, 5 stops everyone."],
  ].map(([t, d]) => [h("dt", { text: t }), h("dd", { text: d })]))),
  h("details", { class: "section", "data-k": "help-cli" }, h("summary", null, icon("chevron", "sm"), "The same things from a terminal"), h("dl", { class: "kv" }, [
    ["Open this app", "rt app"], ["Add it to your app menu", "rt app --install"], ["Ask the table", "rt ask \"your question\""], ["See what needs you", "rt status"], ["Add an AI", "rt seat add opus --model claude-opus-5-5 --app claude-code"],
    ["Start an AI", "rt launch opus"], ["Connect an app", "rt setup codex"], ["Give a goal", "rt goal \"what to build\" --review mid"],
    ["Approve the plan", "rt plan view, then rt plan lock"], ["List tasks", "rt task list"], ["Accept found work", "rt task accept T7"],
    ["Check changes", "rt review get T3, then rt review submit T3 approve"], ["Report a problem", "rt alert raise 3 \"what is wrong\""],
    ["Pause everyone", "rt freeze"], ["Usage", "rt usage"], ["Add a note", "rt memory add \"note\""], ["Check the setup", "rt doctor"],
  ].map(([a, b]) => [h("dt", { text: a }), h("dd", { class: "mono", text: b })]))),
  sec("Where things are", h("dl", { class: "kv" },
    h("dt", { text: "Project" }), h("dd", { class: "mono", text: st.project.root }),
    h("dt", { text: "Roundtable's data" }), h("dd", { class: "mono", text: st.project.home }),
    h("dt", { text: "AIs' copies" }), h("dd", { class: "mono pre", text: st.seats.filter(x => x.worktree).map(x => x.worktree).join("\n") || "none yet" }))),
  sec("Credits", h("p", { class: "muted", text: "Planning together and asking the table borrow from Andrej Karpathy's LLM Council (independent answers, anonymous peer ranking and a chairman). Task tracking learns from Steve Yegge's Beads and Gas Town, and messaging from MCP Agent Mail. Text is set in Atkinson Hyperlegible Next by the Braille Institute (SIL Open Font License)." })),
  h("p", { class: "faint", text: "Roundtable v" + st.project.version })] });

/* ---------------------------------------------------------------- another project */

PAGES.switch = st => {
  const input = h("input", { type: "text", id: "switch-folder", "data-k": "switch-folder", placeholder: "/home/you/projects/app", spellcheck: "false" });
  return { title: "Open another project", body: [
    h("p", { class: "muted", text: "Roundtable keeps one table per project folder. Open another folder here; if it has no table yet, you can set one up there next." }),
    h("dl", { class: "kv" }, h("dt", { text: "Now open" }), h("dd", { class: "mono", text: st.project.root })),
    h("div", { class: "field" }, h("label", { for: "switch-folder", text: "Folder" }),
      h("div", { class: "row" }, h("div", { class: "grow" }, input),
        h("button", { type: "button", onclick: e => browseFolder(input, e.currentTarget, f => special("open", { folder: f }, { title: "Opened", after: () => go("#/room") })) }, icon("folder", "sm"), "Browse…"),
        h("button", { class: "go", type: "button", onclick: e => special("open", { folder: input.value.trim() }, { button: e.currentTarget, title: "Opened", after: () => go("#/room") }) }, "Open"))),
    st.recent && st.recent.length ? sec("Recent projects", h("ul", { class: "tasklist" }, st.recent.filter(r => r.root !== st.project.root).map(r => h("li", null,
      h("button", { type: "button", onclick: e => special("open", { folder: r.root }, { button: e.currentTarget, title: "Opened " + r.name, after: () => go("#/room") }) },
        icon("folder", "sm"), h("span", { class: "t" }, h("strong", { text: r.name }), h("span", { text: r.root }))))))) : null] };
};

/* ---------------------------------------------------------------- first visit: three steps */

function skipKey() { return "rt.skipWelcome:" + (S.project ? S.project.root : ""); }
function inWelcome() {
  if (S.mode !== "project") return false;
  if (route.page === "welcome") return true;
  return !S.seats.length && !store(skipKey());
}
function welcomeStep() { return ui.wstep || (!S.seats.length ? 1 : S.plan ? 3 : 2); }

function welcomeArt(steps, at, title, lead) {
  return h("aside", { class: "welcome-art" },
    h("div", { class: "brand" }, h("img", { src: "/icon.svg", alt: "", width: "28", height: "28" }), "Roundtable"),
    h("h1", { text: title }), h("p", { text: lead }),
    steps ? h("ol", { class: "wsteps", "aria-label": "Steps" }, steps.map((label, i) => h("li", { class: i + 1 < at ? "done" : i + 1 === at ? "now" : "", "aria-current": i + 1 === at ? "step" : null },
      h("span", { class: "n", "aria-hidden": "true" }, i + 1 < at ? icon("check", "sm") : String(i + 1)), h("span", { class: "label", text: label })))) : null,
    h("div", { class: "table-art" }, tableArt(S.seats || [], true)));
}

PAGES.welcome = st => welcomeScreen(st);

function welcomeScreen(st) {
  const step = welcomeStep();
  const toRoom = () => { store(skipKey(), true); ui.wstep = 0; go("#/room"); };
  let main;
  if (step === 1) main = [
    h("h2", { text: "Which AIs should work together?" }),
    h("p", { class: "lead", text: "Pick the apps you already use. Each AI runs there with your own subscription, so there are no API keys. Two from different companies catch each other's mistakes." }),
    picker(st, () => { ui.wstep = 2; go("#/welcome"); }),
    h("div", { class: "row" },
      st.seats.length ? h("button", { class: "go", type: "button", onclick: () => { ui.wstep = 2; go("#/welcome"); } }, "Next: start them", icon("chevron", "sm")) : null,
      h("button", { class: "ghost", type: "button", onclick: toRoom }, st.seats.length ? "Go to the room" : "Skip for now and look around"))];
  else if (step === 2) main = [
    h("h2", { text: "Start each one" }),
    h("p", { class: "lead", text: "Each AI works in its own copy of your project, so your folder is never edited directly. Easiest: let Roundtable run them in the background; it wakes them whenever there is work. Or open each one in a terminal and watch it there." }),
    h("div", null, st.seats.map(x => {
      const info = ui.started[x.handle];
      return h("div", { class: "joinrow" }, avatar(x.handle, "lg"),
        h("div", { class: "who" }, h("strong", { text: x.handle }), h("p", { class: "faint", text: `${prettyModel(x.model)} · ${x.app_label}` }),
          info && !x.joined_ever ? startedBox(x, info) : null),
        running(x) ? h("span", { class: "pill ok" }, icon("check", "sm"), "Runs in the background")
          : x.joined_ever ? h("span", { class: "pill ok" }, icon("check", "sm"), "At the table")
          : h("div", { class: "row" },
            x.can_run ? h("button", { class: "go", type: "button", onclick: e => runSeats([x.handle], e.currentTarget) }, icon("play", "sm"), "Run in the background") : null,
            h("button", { class: x.can_run || info ? "" : "go", type: "button", onclick: e => startSeat(x, e.currentTarget) },
              icon(x.start.kind === "terminal" ? "terminal" : x.start.kind === "desktop" ? "desktop" : "code", "sm"), x.can_run ? "Open a terminal" : info ? "Start again" : startLabel(x))));
    })),
    h("p", { class: "faint", text: "Background runs use your own Claude Code and Codex logins: sign in to each app once on this computer first. You can also go on now and start them later." }),
    h("div", { class: "row" },
      h("button", { class: "go", type: "button", onclick: () => { ui.wstep = 3; go("#/welcome"); } }, "Next: give them a goal", icon("chevron", "sm")),
      h("button", { class: "ghost", type: "button", onclick: () => { ui.wstep = 1; go("#/welcome"); } }, icon("plus", "sm"), "Add another AI"),
      h("button", { class: "ghost", type: "button", onclick: toRoom }, "Go to the room"))];
  else main = isLivePlan(st.plan) ? [
    h("h2", { text: "They're on it" }),
    h("p", { class: "lead", text: "Your AIs have a goal. Watch them plan in the room; the plan comes to you when they agree." }),
    h("div", { class: "row" }, h("button", { class: "go", type: "button", onclick: toRoom }, "Go to the room", icon("chevron", "sm")))] : [
    h("h2", { text: "What should they build?" }),
    h("p", { class: "lead", text: "Each AI writes its own plan, they comment on each other's without knowing who wrote which, and one plan comes back to you. Nothing is built before you approve it." }),
    goalForm(st, toRoom),
    h("div", { class: "row" }, h("button", { class: "ghost", type: "button", onclick: () => { ui.wstep = 2; render(); } }, icon("back", "sm"), "Back"),
      h("button", { class: "ghost", type: "button", onclick: toRoom }, "Later; show me the room"))];
  return h("div", { class: "welcome" },
    welcomeArt(["Choose your AIs", "Start them", "Give them a goal"], step, "Your AIs, around one table",
      "Claude, GPT, Gemini and others plan, build and check one project together. You set the goal and make the calls."),
    h("main", { class: "welcome-main" }, h("div", { class: "stack" }, main)));
}

/* ---------------------------------------------------------------- a folder without Roundtable yet */

function setupScreen(st) {
  const f = st.setup;
  const notes = [];
  let can = f.exists;
  if (!f.exists) notes.push(note("This folder does not exist.", "warn"));
  else if (f.worktree_of) { can = false; notes.push(note(`This is one AI's own copy of a project. Set up Roundtable in the main folder instead: ${f.worktree_of}`, "warn")); }
  else if (f.inside) { can = false; notes.push(note(`This folder is inside a git repository. Set up Roundtable at its top folder: ${f.toplevel}`, "warn")); }
  else if (!f.git) notes.push(note("This folder has no git. Roundtable still works, but every AI shares this one folder. For a separate copy per AI, checked changes and automatic merges, run git init here and make a first commit, then reload.", "warn"));
  else if (!f.has_commits) notes.push(note("This git repository has no commits yet. Make a first commit before adding AIs that write code: their copies start from it.", "warn"));
  else notes.push(note(`Git repository on branch ${f.branch || "(detached)"}. Each AI that writes code gets its own copy next to this folder, and finished work is merged into ${f.branch || "your branch"}.`, "ok"));
  const folderIn = h("input", { type: "text", id: "open-folder", "data-k": "open-folder", value: f.folder, spellcheck: "false", autocomplete: "off" });
  const art = welcomeArt(null, 0, "Bring your AIs to one table", "Several AI models plan, build and check this project together, each in its own app. Roundtable only adds a hidden .roundtable folder; it never changes your files.");
  return h("div", { class: "welcome" }, art, h("main", { class: "welcome-main" }, h("div", { class: "stack" },
    h("h2", { text: "Set up Roundtable here" }),
    h("dl", { class: "kv" }, h("dt", { text: "Folder" }), h("dd", { class: "mono", text: f.folder })),
    notes,
    h("div", { class: "row" }, h("button", { class: "go", type: "button", disabled: !can, onclick: e => special("init", { folder: f.folder }, { button: e.currentTarget, title: "Roundtable is set up" }) }, "Set up Roundtable in this folder")),
    h("details", { "data-k": "setup-other" }, h("summary", null, icon("chevron", "sm"), "Use another folder"),
      h("div", { class: "field" }, h("label", { for: "open-folder", text: "Folder" }),
        h("div", { class: "row" }, h("div", { class: "grow" }, folderIn),
          h("button", { type: "button", onclick: e => browseFolder(folderIn, e.currentTarget, f => special("open", { folder: f }, { title: "Opened" })) }, icon("folder", "sm"), "Browse…"),
          h("button", { type: "button", onclick: e => special("open", { folder: folderIn.value.trim() }, { button: e.currentTarget, title: "Opened" }) }, "Open")))),
    st.recent && st.recent.length ? h("section", { class: "section" }, h("h2", { text: "Recent projects" }),
      h("ul", { class: "tasklist" }, st.recent.map(r => h("li", null, h("button", { type: "button", onclick: e => special("open", { folder: r.root }, { button: e.currentTarget, title: "Opened " + r.name }) },
        icon("folder", "sm"), h("span", { class: "t" }, h("strong", { text: r.name }), h("span", { text: r.root }))))))) : null)));
}

/* ---------------------------------------------------------------- boot */

applyTheme();
route = parseRoute();
window.addEventListener("hashchange", () => {
  route = parseRoute();
  if (taskRoute()) loadTask(taskRoute()).then(render);
  if (route.page === "ai" && route.sub) loadActivity(route.sub).then(render);
  render();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && DRAWERS.includes(route.page) && S && S.mode === "project" && !inWelcome()) { e.preventDefault(); close(); }
});
refresh(true);
setInterval(() => { if (document.visibilityState === "visible") refresh(false); }, 3000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(false); });
