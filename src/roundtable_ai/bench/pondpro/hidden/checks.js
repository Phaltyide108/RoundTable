// Hidden checks for the `pondpro` benchmark task: the physics measured against TASK.md's numbers.
// Run inside the contender's page once window.pond exists; returns { checkName: [passed, detail] }.
async () => {
  const R = {};
  const ok = (name, cond, detail) => { R[name] = [!!cond, String(detail || "")]; };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const num = v => typeof v === "number" && isFinite(v);
  const mean = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN;
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
  const hdist = (a, b) => Math.hypot(a.x - b.x, a.z - b.z);
  const len = v => Math.hypot(v.x, v.y, v.z);
  const copy = v => ({ x: v.x, y: v.y, z: v.z });
  const cosv = (a, b) => { const la = len(a), lb = len(b); return la && lb ? Math.max(-1, Math.min(1, (a.x * b.x + a.y * b.y + a.z * b.z) / (la * lb))) : 1; };
  const P = window.pond;
  const dt = 1 / 60;
  const run = (n, each) => { for (let i = 0; i < n; i++) { P.step(dt); if (each) each(i); } };
  const finiteFish = () => P.fish.every(f => ["x", "y", "z"].every(k => num(f.position[k]) && num(f.velocity[k])));
  const need = ["step", "addRipple", "dropFood", "waterHeight", "setFishCount", "setHeron", "reset"];
  const has = P && need.every(k => typeof P[k] === "function") && ["fish", "food", "lilyPads", "stones"].every(k => Array.isArray(P[k]));
  ok("test_interface", has, has ? "window.pond is complete" : "missing: " + (P ? need.filter(k => typeof P[k] !== "function").concat(["fish", "food", "lilyPads", "stones"].filter(k => !Array.isArray(P[k]))).join(", ") : "window.pond"));
  if (!has) return R;
  const canvas = document.querySelector("canvas");
  ok("canvas_fills_window", canvas && canvas.clientWidth >= innerWidth * 0.95 && canvas.clientHeight >= innerHeight * 0.95, canvas ? `${canvas.clientWidth}x${canvas.clientHeight}` : "no canvas");
  ok("bounds", P.bounds && P.bounds.radius === 10 && P.bounds.depth === 3, JSON.stringify(P.bounds));

  // it animates by itself, smoothly
  P.paused = false;
  let frames = 0;
  const t0 = performance.now();
  await new Promise(res => { const f = () => { frames++; if (performance.now() - t0 < 2000) requestAnimationFrame(f); else res(); }; requestAnimationFrame(f); });
  ok("frame_rate", frames / 2 >= 10, `${(frames / 2).toFixed(0)} fps (headless, software graphics)`);
  P.paused = true;
  await sleep(100);

  // determinism
  P.reset(7);
  ok("reset_gives_18_fish", P.fish.length === 18, `${P.fish.length} fish after reset`);
  run(300);
  const a = P.fish.map(f => copy(f.position));
  P.reset(7);
  run(300);
  const b = P.fish.map(f => copy(f.position));
  P.reset(8);
  run(300);
  const c = P.fish.map(f => copy(f.position));
  const same = a.length === b.length && a.every((p, i) => dist(p, b[i]) < 1e-9);
  const differs = a.length === c.length && a.some((p, i) => dist(p, c[i]) > 1e-3);
  ok("deterministic_with_a_seed", same && differs, same ? (differs ? "same seed, same pond; other seed, other pond" : "a different seed gave the same pond") : "the same seed gave different positions");

  // stones
  P.reset(7);
  const st = P.stones;
  const stonesOk = st.length >= 5 && st.every(s => s && s.position && num(s.radius) && s.radius >= 0.4 && s.radius <= 1.0
    && Math.hypot(s.position.x, s.position.z) + s.radius <= 10.01 && s.position.y - s.radius <= -2.6);
  ok("stones_on_the_bottom", stonesOk, `${st.length} stones` + (st[0] ? `, e.g. radius ${Number(st[0].radius).toFixed(2)} at y ${Number(st[0].position.y).toFixed(2)}` : ""));

  // 20 s of schooling with 18 fish
  let outside = 0, near = 0, inStone = 0, slow = 0, fast = 0, sharp = 0, worstTurn = 0, samples = 0;
  let minSep = Infinity;
  const nn = [], align = [];
  let prevV = P.fish.map(f => copy(f.velocity));
  run(1200, i => {
    const vs = P.fish.map(f => copy(f.velocity));
    if (i >= 120) {
      vs.forEach((v, k) => { const turn = Math.acos(cosv(prevV[k], v)) / dt; worstTurn = Math.max(worstTurn, turn); if (turn > 3 * 1.25) sharp++; });
    }
    prevV = vs;
    if (i < 300 || i % 6) return;
    const F = P.fish.map(f => ({ p: copy(f.position), v: copy(f.velocity) }));
    for (const f of F) {
      samples++;
      const r = Math.hypot(f.p.x, f.p.z);
      if (!(r <= 10 && f.p.y <= 0 && f.p.y >= -3)) outside++;
      else if (r > 10 - 0.25 || f.p.y > -0.25 || f.p.y < -3 + 0.25) near++;
      for (const s of P.stones) if (dist(f.p, s.position) < s.radius + 0.15) inStone++;
      const sp = len(f.v);
      if (sp < 0.18) slow++;
      if (sp > 2.1) fast++;
    }
    for (let x = 0; x < F.length; x++) {
      let best = Infinity, bi = -1;
      for (let y = 0; y < F.length; y++) if (x !== y) { const d = dist(F[x].p, F[y].p); if (d < best) { best = d; bi = y; } }
      nn.push(best);
      minSep = Math.min(minSep, best);
      if (bi >= 0) align.push(cosv(F[x].v, F[bi].v));
    }
  });
  ok("fish_stay_in_the_pond", outside === 0 && finiteFish(), `${outside} of ${samples} positions outside` + (finiteFish() ? "" : " (some became NaN)"));
  ok("fish_keep_0_3_m_from_edges", near <= samples * 0.01, `${near} of ${samples} positions within 0.25 m of the wall, bottom or surface`);
  ok("fish_swim_around_stones", inStone === 0, `${inStone} positions inside or touching a stone`);
  ok("speed_between_0_2_and_2_m_s", slow + fast <= samples * 0.01, `${slow} too slow, ${fast} too fast of ${samples}`);
  ok("turning_at_most_3_rad_s", sharp <= 18 * 1080 * 0.005, `fastest turn ${worstTurn.toFixed(2)} rad/s; ${sharp} steps over the limit`);
  ok("no_two_fish_closer_than_0_4_m", minSep >= 0.38, `closest pair ${minSep.toFixed(3)} m`);
  ok("alignment_and_cohesion", mean(align) > 0.3 && mean(nn) < 3.5, `heading agreement ${mean(align).toFixed(2)}, mean nearest neighbour ${mean(nn).toFixed(2)} m`);

  // water: measured without fish
  P.reset(7);
  P.setFishCount(0);
  run(120);
  P.addRipple(0, 0, 1);
  let best = 0, bestT = -1;
  // wave energy: motion (from two heights a step apart) plus slope, on a 0.5 m grid inside 8 m
  const pts = [];
  for (let x = -8; x <= 8; x += 0.5) for (let z = -8; z <= 8; z += 0.5) if (x * x + z * z < 64) pts.push([x, z]);
  const heights = () => pts.map(([x, z]) => P.waterHeight(x, z));
  const slope2 = () => { let s2 = 0; for (const [x, z] of pts) { const gx = (P.waterHeight(x + 0.25, z) - P.waterHeight(x - 0.25, z)) / 0.5, gz = (P.waterHeight(x, z + 0.25) - P.waterHeight(x, z - 0.25)) / 0.5; s2 += gx * gx + gz * gz; } return s2; };
  const energy = [];
  for (let i = 1; i <= 720; i++) {
    const before = i % 12 === 0 ? heights() : null;
    P.step(dt);
    if (i <= 240) {
      const m = (Math.abs(P.waterHeight(4, 0)) + Math.abs(P.waterHeight(0, 4)) + Math.abs(P.waterHeight(-4, 0)) + Math.abs(P.waterHeight(0, -4))) / 4;
      if (m > best) { best = m; bestT = i * dt; }
    }
    if (before) {
      const after = heights();
      let kin = 0;
      after.forEach((hh, k) => { kin += ((hh - before[k]) / dt) ** 2; });
      energy.push([i * dt, kin + 4.0 * slope2()]);
    }
  }
  ok("waves_travel_at_2_m_s", bestT >= 1.5 && bestT <= 2.5, `the crest reached 4 m after ${bestT.toFixed(2)} s (2.0 s expected)`);
  const w = (t1, t2) => mean(energy.filter(([t]) => t >= t1 && t <= t2).map(([, e]) => e));
  const ratio = Math.sqrt(w(9, 12) / w(3, 6));
  ok("amplitude_halves_every_3_s", ratio >= 0.15 && ratio <= 0.4, `6 s later the waves were ${(ratio * 100).toFixed(0)}% as high (25% expected)`);
  P.setFishCount(0);
  for (let k = 0; k < 60; k++) { const an = k * 2.399, r = 1 + (k % 8); P.addRipple(r * Math.cos(an), r * Math.sin(an), 3); if (k % 6 === 0) P.step(dt); }
  let peak = 0, bad = false;
  const probe = () => { let m = 0; for (let x = -9; x <= 9; x += 0.75) for (let z = -9; z <= 9; z += 0.75) if (x * x + z * z < 81) { const h = P.waterHeight(x, z); if (!num(h)) bad = true; else m = Math.max(m, Math.abs(h)); } return m; };
  for (let i = 0; i < 1800; i++) { P.step(dt); if (i % 60 === 0) peak = Math.max(peak, probe()); }
  const end = probe();
  ok("water_stays_stable", !bad && peak < 1.5 && end < peak, bad ? "the water turned into NaN" : `after 60 strong ripples: highest ${peak.toFixed(3)} m, 30 s later ${end.toFixed(3)} m`);

  // lily pads
  P.reset(7);
  P.setFishCount(0);
  P.addRipple(0, 0, 2);
  let off = 0;
  const ys = P.lilyPads.map(() => []);
  run(120, () => P.lilyPads.forEach((p, k) => { ys[k].push(p.position.y); off = Math.max(off, Math.abs(p.position.y - P.waterHeight(p.position.x, p.position.z))); }));
  const bob = ys.length ? Math.max(...ys.map(v => Math.max(...v) - Math.min(...v))) : 0;
  ok("lily_pads_ride_the_waves", P.lilyPads.length >= 4 && off < 0.06 && bob > 0.0005, `${P.lilyPads.length} pads, off the water by ${off.toFixed(3)} m, bobbing ${bob.toFixed(4)} m`);

  // food physics without fish
  P.reset(7);
  P.setFishCount(0);
  P.dropFood(3, 0);
  const pel = P.food[P.food.length - 1];
  let floatOff = 0, y3 = NaN, y5 = NaN;
  for (let i = 1; i <= 1200 && pel; i++) {
    P.step(dt);
    if (i <= 108) floatOff = Math.max(floatOff, Math.abs(pel.position.y - P.waterHeight(pel.position.x, pel.position.z)));
    if (i === 180) y3 = pel.position.y;
    if (i === 300) y5 = pel.position.y;
  }
  const sink = (y3 - y5) / 2;
  ok("pellet_floats_2_s", pel && floatOff < 0.06, pel ? `off the surface by up to ${floatOff.toFixed(3)} m in its first 1.8 s` : "no pellet");
  ok("pellet_sinks_at_0_25_m_s", sink >= 0.2 && sink <= 0.3, `sank ${num(sink) ? sink.toFixed(3) : "?"} m/s between 3 s and 5 s`);
  ok("pellet_rests_on_the_bottom", pel && pel.position.y >= -3.01 && pel.position.y <= -2.85, pel ? `at y ${pel.position.y.toFixed(3)} after 20 s` : "");

  // fish eat
  P.reset(7);
  run(120);
  const f0 = P.fish[0].position;
  const nFood = P.food.length;
  P.dropFood(f0.x * 0.7, f0.z * 0.7);
  let eaten = -1;
  run(900, i => { if (eaten < 0 && P.food.length <= nFood) eaten = i; });
  ok("fish_find_and_eat_food", eaten >= 0, eaten >= 0 ? `eaten after ${(eaten / 60).toFixed(1)} s` : "still there after 15 s");

  // the heron
  P.reset(7);
  run(300);
  const cx = mean(P.fish.map(f => f.position.x)), cz = mean(P.fish.map(f => f.position.z));
  const rr = Math.hypot(cx, cz), k = rr > 8 ? 8 / rr : 1;
  const hx = cx * k, hz = cz * k;
  P.setHeron(hx, hz);
  const heronOk = P.heron && P.heron.position && Math.abs(P.heron.position.x - hx) < 0.01 && Math.abs(P.heron.position.z - hz) < 0.01;
  const nearIdx = P.fish.map((f, i) => [i, hdist(f.position, { x: hx, z: hz })]).filter(([, d]) => d < 4).map(([i]) => i);
  const d0 = mean(nearIdx.map(i => hdist(P.fish[i].position, { x: hx, z: hz })));
  let maxSp = 0;
  run(120, () => nearIdx.forEach(i => { maxSp = Math.max(maxSp, len(P.fish[i].velocity)); }));
  const d1 = mean(nearIdx.map(i => hdist(P.fish[i].position, { x: hx, z: hz })));
  ok("fish_flee_the_heron", heronOk && nearIdx.length > 0 && d1 - d0 >= 1.0, `${nearIdx.length} fish within 4 m moved from ${num(d0) ? d0.toFixed(2) : "?"} to ${num(d1) ? d1.toFixed(2) : "?"} m away in 2 s`);
  ok("fleeing_is_faster_up_to_3_m_s", maxSp > 2.05 && maxSp <= 3.1, `fastest fleeing fish ${maxSp.toFixed(2)} m/s`);
  P.setHeron(null);
  ok("heron_can_leave", P.heron === null || P.heron === undefined, `heron is ${JSON.stringify(P.heron)}`);

  // 200 fish
  P.reset(7);
  P.setFishCount(200);
  const n200 = P.fish.length;
  const ts = performance.now();
  run(60);
  const ms = performance.now() - ts;
  let out200 = 0, sep200 = Infinity;
  run(300, i => {
    if (i % 30) return;
    const F = P.fish.map(f => copy(f.position));
    F.forEach(p => { if (!(Math.hypot(p.x, p.z) <= 10 && p.y <= 0 && p.y >= -3)) out200++; });
    for (let x = 0; x < F.length; x += 4) for (let y = 0; y < F.length; y++) if (x !== y) sep200 = Math.min(sep200, dist(F[x], F[y]));
  });
  ok("200_fish_simulate_fast", n200 === 200 && ms < 600, `${n200} fish: one simulated second took ${ms.toFixed(0)} ms`);
  ok("200_fish_stay_in_and_apart", n200 === 200 && out200 === 0 && sep200 >= 0.3, `${out200} outside, closest pair ${sep200.toFixed(2)} m`);
  P.paused = false;
  frames = 0;
  const t2 = performance.now();
  await new Promise(res => { const f = () => { frames++; if (performance.now() - t2 < 2000) requestAnimationFrame(f); else res(); }; requestAnimationFrame(f); });
  P.paused = true;
  ok("200_fish_render_smoothly", frames / 2 >= 8, `${(frames / 2).toFixed(0)} fps with 200 fish (headless, software graphics)`);

  // a click on the water
  P.reset(7);
  run(60);
  const foodBefore = P.food.length;
  const probe2 = () => { let m = 0; for (let x = -9; x <= 9; x += 1.5) for (let z = -9; z <= 9; z += 1.5) if (x * x + z * z < 81) m = Math.max(m, Math.abs(P.waterHeight(x, z))); return m; };
  const quiet = probe2();
  const rect = canvas.getBoundingClientRect();
  const cxp = rect.left + rect.width / 2, cyp = rect.top + rect.height * 0.55;
  const opt = { bubbles: true, cancelable: true, clientX: cxp, clientY: cyp, button: 0, buttons: 1, pointerId: 1, pointerType: "mouse", isPrimary: true };
  canvas.dispatchEvent(new PointerEvent("pointerdown", opt));
  canvas.dispatchEvent(new MouseEvent("mousedown", opt));
  canvas.dispatchEvent(new PointerEvent("pointerup", Object.assign({}, opt, { buttons: 0 })));
  canvas.dispatchEvent(new MouseEvent("mouseup", Object.assign({}, opt, { buttons: 0 })));
  canvas.dispatchEvent(new MouseEvent("click", Object.assign({}, opt, { buttons: 0 })));
  await sleep(100);
  P.step(dt);
  P.step(dt);
  ok("click_ripples_and_feeds", P.food.length > foodBefore && probe2() > quiet + 0.002, `food ${foodBefore} -> ${P.food.length}, water ${quiet.toFixed(4)} -> ${probe2().toFixed(4)} m`);
  return R;
}
