"""`rt ui`: a small local dashboard (standard library only).

Safety: listens on 127.0.0.1 only; checks the Host header (blocks DNS
rebinding); every action needs a per-run token embedded in the page and a
same-origin request; only a fixed list of human actions is allowed.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import util
from .errors import RTError

ALLOWED_ACTIONS = {
    "admin.freeze", "admin.unfreeze", "admin.config_set", "plan.lock", "plan.continue", "vote.decide",
    "alert.resolve", "alert.set_level", "review.level_decide", "task.merge", "review.submit", "plan.amend_decide",
}


def state(home) -> dict[str, Any]:
    from . import report
    from .context import open_ctx
    from .seats import is_live

    ctx = open_ctx(home, client="dashboard")
    try:
        seats = [{"handle": s["handle"], "model": s["model"], "app": s["app"], "company": s["company"], "status": s["status"],
                  "live": is_live(ctx, s), "seen": util.human_ago(s["last_seen"]), "doing": s["now_doing"] or ""}
                 for s in ctx.db.all("SELECT * FROM seats WHERE status != 'removed' ORDER BY created_at")]
        tasks = [{"id": t["id"], "title": t["title"], "status": t["status"], "owner": t["owner"] or "", "risk": t["risk"]}
                 for t in ctx.db.all("SELECT * FROM tasks ORDER BY seq, id")]
        alerts = [{"id": a["id"], "level": a["level"], "title": a["title"], "status": a["status"], "by": a["raised_by"],
                   "proposed": a["proposed_level"]}
                  for a in ctx.db.all("SELECT * FROM alerts WHERE status != 'resolved' ORDER BY level DESC, id")]
        events = [{"at": util.local_hm(e["at"]), "actor": e["actor"], "text": e["text"], "level": e["level"]}
                  for e in ctx.db.all("SELECT * FROM events ORDER BY id DESC LIMIT 40")]
        plan = ctx.db.one("SELECT id, goal, stage, chair, version FROM plans ORDER BY id DESC LIMIT 1")
        votes = [{"id": v["id"], "topic": v["topic"], "options": util.jload(v["options"], []), "status": v["status"]}
                 for v in ctx.db.all("SELECT * FROM votes WHERE status IN ('open','tied') ORDER BY id")]
        reqs = [{"id": q["id"], "task": q["task"], "level": q["level"], "seat": q["seat"], "reason": q["reason"]}
                for q in ctx.db.all("SELECT * FROM level_requests WHERE status = 'pending'")]
        return {
            "project": ctx.setting("project", "name") or ctx.root.name,
            "review": ctx.setting("review", "level"),
            "frozen": ctx.db.meta_get("frozen") == "1",
            "plan": dict(plan) if plan else None,
            "seats": seats, "tasks": tasks, "alerts": alerts, "events": events, "votes": votes, "requests": reqs,
            "waiting": report.waiting_on_human(ctx),
        }
    finally:
        ctx.close()


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Roundtable</title><style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e3e2dc;--acc:#3c5bd6;--warn:#b26b00;--bad:#b42318;--good:#1f7a4d}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecebe6;--mute:#a3a29b;--line:#34332f;--acc:#8ea2ff;--warn:#f0a94b;--bad:#ff8a80;--good:#6fd39c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0}h2{font-size:14px;margin:0 0 8px;color:var(--mute);font-weight:600;text-transform:none}
main{display:grid;gap:16px;padding:16px 20px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:4px 0;border-bottom:1px solid var(--line)}.row:last-child{border-bottom:0}
.pill{font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid var(--line);color:var(--mute)}
.live{color:var(--good);border-color:var(--good)}.l5,.l4{color:var(--bad);border-color:var(--bad)}.l3{color:var(--warn);border-color:var(--warn)}
button,select{font:inherit;padding:4px 10px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff}button.danger{border-color:var(--bad);color:var(--bad)}
.mute{color:var(--mute)}#msg{min-height:1.5em;padding:0 20px;color:var(--acc)}.stop{color:var(--bad);font-weight:600}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}.col h3{font-size:12px;margin:0 0 4px;color:var(--mute)}
.task{font-size:13px;padding:4px 6px;border:1px solid var(--line);border-radius:6px;margin-bottom:4px}
</style></head><body>
<header><div><h1 id="title">Roundtable</h1><div class="mute" id="plan"></div></div>
<div class="row" style="border:0"><label>Review depth <select id="level"><option>low</option><option>mid</option><option>high</option></select></label>
<button id="freeze" class="danger">Stop all seats</button></div></header>
<div id="msg"></div>
<main>
<section><h2>Waiting on you</h2><div id="waiting"></div></section>
<section><h2>Seats</h2><div id="seats"></div></section>
<section style="grid-column:1/-1"><h2>Tasks</h2><div class="cols" id="tasks"></div></section>
<section><h2>Alerts</h2><div id="alerts"></div></section>
<section><h2>Recent activity</h2><div id="events"></div></section>
</main>
<script>
const TOKEN = "__TOKEN__";
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function act(op, params){
  const r = await fetch("/api/action", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({token:TOKEN, op, params})});
  const j = await r.json(); $("msg").textContent = j.ok ? j.text.split("\n")[0] : ("Not done: " + j.message + (j.hint ? " — " + j.hint : ""));
  load();
}
function button(label, op, params, cls){ const b=document.createElement("button"); b.textContent=label; if(cls) b.className=cls; b.onclick=()=>act(op, params); return b; }
async function load(){
  let s; try { s = await (await fetch("/api/state")).json(); } catch(e){ $("msg").textContent="Dashboard lost contact with rt ui."; return; }
  if (s.error){ $("msg").textContent = s.error; return; }
  $("title").textContent = "Roundtable · " + s.project;
  $("plan").innerHTML = s.plan ? `P${s.plan.id} [${esc(s.plan.stage)}] ${esc(s.plan.goal)}` + (s.frozen ? ' · <span class="stop">ALL SEATS STOPPED</span>' : "") : "No plan yet — rt goal \"...\"";
  $("level").value = s.review;
  const fb = $("freeze"); fb.textContent = s.frozen ? "Resume seats" : "Stop all seats"; fb.onclick = () => act(s.frozen ? "admin.unfreeze" : "admin.freeze", s.frozen ? {} : {reason:"stopped from the dashboard"});
  const w = $("waiting"); w.innerHTML = "";
  if (s.plan && s.plan.stage === "awaiting_human") w.append(button("Lock plan P"+s.plan.id, "plan.lock", {}, "primary"));
  s.votes.filter(v=>v.status==="tied").forEach(v => { const d=document.createElement("div"); d.className="row"; d.innerHTML=`<span>${esc(v.id)} tied: ${esc(v.topic)}</span>`; v.options.forEach(o=>d.append(button(o,"vote.decide",{id:v.id,choice:o}))); w.append(d); });
  s.requests.forEach(q => { const d=document.createElement("div"); d.className="row"; d.innerHTML=`<span>${esc(q.seat)} asks ${esc(q.level)} review on ${esc(q.task)}: ${esc(q.reason)}</span>`; d.append(button("Approve","review.level_decide",{id:q.id,decision:"approve"}), button("Deny","review.level_decide",{id:q.id,decision:"deny"})); w.append(d); });
  if (s.tasks.some(t=>t.status==="merge_blocked")) w.append(button("Retry merges","task.merge",{}));
  s.waiting.forEach(x => { const d=document.createElement("div"); d.className="row mute"; d.textContent=x; w.append(d); });
  if (!w.children.length) w.innerHTML = '<span class="mute">Nothing. The seats are working.</span>';
  $("seats").innerHTML = s.seats.map(x => `<div class="row"><b>${esc(x.handle)}</b><span class="mute">${esc(x.model)} · ${esc(x.app)}</span><span class="pill ${x.live?"live":""}">${x.status!=="active"?esc(x.status):(x.live?"live":"idle · "+esc(x.seen))}</span>${x.doing?`<span class="mute">${esc(x.doing)}</span>`:""}</div>`).join("") || '<span class="mute">No seats. rt seat add ...</span>';
  const order = ["ready","claimed","proving","in_review","changes_requested","merge_blocked","done","open","cancelled"];
  $("tasks").innerHTML = order.filter(st => s.tasks.some(t=>t.status===st)).map(st => `<div class="col"><h3>${st.replace("_"," ")} (${s.tasks.filter(t=>t.status===st).length})</h3>` + s.tasks.filter(t=>t.status===st).map(t=>`<div class="task"><b>${esc(t.id)}</b> ${esc(t.title)}<div class="mute">${esc(t.owner)}${t.risk==="high"?" · risky":""}</div></div>`).join("") + `</div>`).join("") || '<span class="mute">No tasks yet.</span>';
  const al = $("alerts"); al.innerHTML = "";
  s.alerts.forEach(a => { const d=document.createElement("div"); d.className="row"; d.innerHTML=`<span class="pill l${a.level}">L${a.level}</span><span>${esc(a.id)} ${esc(a.title)} <span class="mute">by ${esc(a.by)}</span></span>`; d.append(button("Resolve","alert.resolve",{id:a.id,resolution:"resolved by the human from the dashboard"})); al.append(d); });
  if (!s.alerts.length) al.innerHTML = '<span class="mute">No open alerts.</span>';
  $("events").innerHTML = s.events.map(e => `<div class="row"><span class="mute">${esc(e.at)}</span><b>${esc(e.actor)}</b><span>${esc(e.text)}</span></div>`).join("");
}
$("level").onchange = e => act("admin.config_set", {key:"review.level", value:e.target.value});
load(); setInterval(load, 5000);
</script></body></html>"""


def make_handler(home, token: str, port_ref: dict):
    from . import dispatch

    class Handler(BaseHTTPRequestHandler):
        server_version = "Roundtable"

        def log_message(self, fmt: str, *args) -> None:  # quiet
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{port_ref['port']}", f"localhost:{port_ref['port']}")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._json(403, {"error": "bad host"})
            if self.path in ("/", "/index.html"):
                return self._send(200, PAGE.replace("__TOKEN__", token).encode("utf-8"), "text/html; charset=utf-8")
            if self.path == "/api/state":
                try:
                    return self._json(200, state(home))
                except RTError as exc:
                    return self._json(200, {"error": exc.render()})
            return self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._host_ok():
                return self._json(403, {"ok": False, "message": "bad host"})
            origin = self.headers.get("Origin")
            if origin and origin.lower() not in (f"http://127.0.0.1:{port_ref['port']}", f"http://localhost:{port_ref['port']}"):
                return self._json(403, {"ok": False, "message": "cross-site request refused"})
            if self.path != "/api/action":
                return self._json(404, {"ok": False, "message": "not found"})
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 100_000)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"ok": False, "message": "bad request"})
            if not secrets.compare_digest(str(body.get("token", "")), token):
                return self._json(403, {"ok": False, "message": "missing or wrong token; reload the page"})
            op = body.get("op")
            params = body.get("params") or {}
            if op not in ALLOWED_ACTIONS or not isinstance(params, dict):
                return self._json(400, {"ok": False, "message": f"action {op!r} is not available here"})
            if op == "admin.config_set" and params.get("key") != "review.level":
                return self._json(400, {"ok": False, "message": "only the review depth can be changed here; use rt config set"})
            try:
                res = dispatch.call(op, params, home=home, as_human=True, client="dashboard")
                return self._json(200, {"ok": True, "text": res.text})
            except RTError as exc:
                return self._json(200, exc.to_dict())

    return Handler


def serve(home, port: int, *, open_browser: bool = True, ready: threading.Event | None = None, server_ref: dict | None = None) -> int:
    token = secrets.token_urlsafe(24)
    port_ref = {"port": port}
    httpd = None
    for p in range(port, port + 20):
        try:
            port_ref["port"] = p
            httpd = ThreadingHTTPServer(("127.0.0.1", p), make_handler(home, token, port_ref))
            break
        except OSError:
            continue
    if httpd is None:
        raise RTError("conflict", f"ports {port}-{port + 19} are all busy", "pass another: rt ui --port 9000")
    if server_ref is not None:
        server_ref.update({"httpd": httpd, "port": port_ref["port"], "token": token})
    url = f"http://127.0.0.1:{port_ref['port']}/"
    print(f"Roundtable dashboard: {url}  (local only; Ctrl+C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    if ready:
        ready.set()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def run_dashboard(home: str | None = None, *, port: int | None = None, open_browser: bool = True) -> int:
    from .context import open_ctx

    ctx = open_ctx(home)
    try:
        h = ctx.home
        p = port or ctx.setting("dashboard", "port")
    finally:
        ctx.close()
    return serve(h, p, open_browser=open_browser)
