// Hidden checks for the `pond` benchmark task. Run inside the contender's page (headless Chrome)
// once window.pond exists; returns { checkName: [passed, detail] }. Each check is one rule of TASK.md.
async () => {
  const R = {};
  const ok = (name, cond, detail) => { R[name] = [!!cond, String(detail || "")]; };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const num = v => typeof v === "number" && isFinite(v);
  const mean = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN;
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
  const cos = (a, b) => { const la = Math.hypot(a.x, a.y, a.z), lb = Math.hypot(b.x, b.y, b.z); return la && lb ? (a.x * b.x + a.y * b.y + a.z * b.z) / (la * lb) : 0; };
  const copy = v => ({ x: v.x, y: v.y, z: v.z });
  const P = window.pond;
  const has = P && typeof P.step === "function" && Array.isArray(P.fish) && typeof P.waterHeight === "function"
    && typeof P.addRipple === "function" && typeof P.dropFood === "function" && Array.isArray(P.food) && Array.isArray(P.lilyPads);
  ok("test_interface", has, has ? "window.pond is complete" : "window.pond or one of its members is missing");
  if (!has) return R;
  const canvas = document.querySelector("canvas");
  ok("canvas_fills_window", canvas && canvas.clientWidth >= innerWidth * 0.95 && canvas.clientHeight >= innerHeight * 0.95,
    canvas ? `${canvas.clientWidth}x${canvas.clientHeight} in ${innerWidth}x${innerHeight}` : "no canvas");
  ok("bounds", P.bounds && P.bounds.radius === 10 && P.bounds.depth === 3, JSON.stringify(P.bounds));
  ok("at_least_15_fish", P.fish.length >= 15, `${P.fish.length} fish`);
  ok("fish_have_position_and_velocity", P.fish.length && P.fish.every(f => f.position && f.velocity && ["x", "y", "z"].every(k => num(f.position[k]) && num(f.velocity[k]))), "");

  // it animates by itself
  P.paused = false;
  const before = P.fish.slice(0, 5).map(f => copy(f.position));
  let frames = 0;
  const t0 = performance.now();
  await new Promise(res => { const f = () => { frames++; if (performance.now() - t0 < 2000) requestAnimationFrame(f); else res(); }; requestAnimationFrame(f); });
  const moved = P.fish.slice(0, 5).some((f, i) => dist(f.position, before[i]) > 0.01);
  ok("animates_by_itself", moved, moved ? "fish moved while unpaused" : "fish did not move in 2 s");
  ok("frame_rate", frames / 2 >= 10, `${(frames / 2).toFixed(0)} frames per second in a headless browser (software graphics)`);
  P.paused = true;
  await sleep(150);

  // 20 seconds of schooling, measured after the first 5
  const dt = 1 / 60;
  let outside = 0, near = 0;
  const speeds = [], nn = [], align = [];
  let minSep = Infinity;
  const tSim = performance.now();
  for (let i = 0; i < 1200; i++) {
    P.step(dt);
    if (i >= 300 && i % 10 === 0) {
      const F = P.fish.map(f => ({ p: copy(f.position), v: copy(f.velocity) }));
      for (const f of F) {
        const r = Math.hypot(f.p.x, f.p.z);
        if (r > 10 || f.p.y > 0 || f.p.y < -3) outside++;
        else if (r > 10 - 0.25 || f.p.y > -0.25 || f.p.y < -3 + 0.25) near++;
        speeds.push(Math.hypot(f.v.x, f.v.y, f.v.z));
      }
      for (let a = 0; a < F.length; a++) {
        let best = Infinity, bi = -1;
        for (let b = 0; b < F.length; b++) if (a !== b) { const d = dist(F[a].p, F[b].p); if (d < best) { best = d; bi = b; } }
        nn.push(best);
        minSep = Math.min(minSep, best);
        if (bi >= 0) align.push(cos(F[a].v, F[bi].v));
      }
    }
  }
  const simMs = performance.now() - tSim;
  ok("simulation_is_fast", simMs < 12000, `20 s simulated in ${(simMs / 1000).toFixed(1)} s`);
  ok("fish_stay_in_the_pond", outside === 0, `${outside} fish positions outside the water`);
  ok("fish_keep_off_walls_bottom_surface", near <= speeds.length * 0.02, `${near} of ${speeds.length} positions within 0.25 m of a boundary`);
  const ms = mean(speeds), mx = Math.max(...speeds);
  ok("fish_speed_is_limited", ms >= 0.3 && ms <= 4 && mx <= 6, `mean ${ms.toFixed(2)} m/s, max ${mx.toFixed(2)} m/s`);
  ok("separation", minSep > 0.05 && mean(nn) > 0.3, `closest pair ${minSep.toFixed(2)} m, mean nearest neighbour ${mean(nn).toFixed(2)} m`);
  ok("alignment", mean(align) > 0.3, `nearest neighbours' headings agree ${mean(align).toFixed(2)} (random is about 0)`);
  ok("cohesion", mean(nn) < 3.5, `mean nearest neighbour ${mean(nn).toFixed(2)} m`);

  // the water: a ripple rises, spreads, and dies away
  const ring = () => { let m = 0; for (let a = 0; a < 24; a++) for (const r of [1, 2, 3, 4, 5]) m = Math.max(m, Math.abs(P.waterHeight(3 + r * Math.cos(a / 24 * 2 * Math.PI), r * Math.sin(a / 24 * 2 * Math.PI)))); return m; };
  for (let i = 0; i < 600; i++) P.step(dt);       // let earlier waves settle
  const calm = ring();
  const h0 = P.waterHeight(3, 0);
  P.addRipple(3, 0, 1);
  P.step(dt);
  ok("ripple_rises", Math.abs(P.waterHeight(3, 0) - h0) > 0.005, `height at the ripple changed by ${Math.abs(P.waterHeight(3, 0) - h0).toFixed(4)} m`);
  let far = 0, peak = 0;
  for (let i = 0; i < 90; i++) {
    P.step(dt);
    far = Math.max(far, Math.abs(P.waterHeight(5.5, 0)), Math.abs(P.waterHeight(3, 2.5)), Math.abs(P.waterHeight(0.5, 0)));
    peak = Math.max(peak, ring());
  }
  ok("ripple_spreads", far > 0.002, `2.5 m away it reached ${far.toFixed(4)} m within 1.5 s`);
  for (let i = 0; i < 1200; i++) P.step(dt);
  const late = ring();
  ok("ripple_fades", late < peak * 0.25 + 0.004 && peak > 0.003, `peak ${peak.toFixed(4)} m, 20 s later ${late.toFixed(4)} m (calm water ${calm.toFixed(4)} m)`);

  // lily pads ride the waves
  const pads = P.lilyPads;
  P.addRipple(0, 0, 2);
  const ys = pads.map(() => []);
  let worst = 0;
  for (let i = 0; i < 120; i++) {
    P.step(dt);
    pads.forEach((p, k) => { ys[k].push(p.position.y); worst = Math.max(worst, Math.abs(p.position.y - P.waterHeight(p.position.x, p.position.z))); });
  }
  const bob = Math.max(...ys.map(a => Math.max(...a) - Math.min(...a)));
  ok("lily_pads_ride_the_waves", pads.length >= 4 && worst < 0.06 && bob > 0.0005, `${pads.length} pads, off the water by up to ${worst.toFixed(3)} m, bobbing ${bob.toFixed(4)} m`);

  // food: fish come and eat it
  for (let i = 0; i < 300; i++) P.step(dt);
  const fx = P.fish[0].position;
  const target = { x: fx.x * 0.6, z: fx.z * 0.6 };
  const foodBefore = P.food.length;
  P.dropFood(target.x, target.z);
  const pellet = P.food[P.food.length - 1];
  const nearest = () => pellet ? Math.min(...P.fish.map(f => dist(f.position, pellet.position))) : Infinity;
  const d0 = nearest();
  let dmin = d0, eatenAt = -1;
  for (let i = 0; i < 900; i++) {
    P.step(dt);
    if (P.food.length <= foodBefore) { eatenAt = i; break; }
    dmin = Math.min(dmin, nearest());
  }
  ok("food_attracts_fish", P.food.length === foodBefore + 1 || eatenAt >= 0, `${P.food.length - foodBefore} pellet(s) after dropFood`);
  ok("fish_swim_to_food", eatenAt >= 0 || dmin < d0 * 0.6, `nearest fish went from ${d0.toFixed(2)} m to ${dmin.toFixed(2)} m`);
  ok("food_gets_eaten", eatenAt >= 0, eatenAt >= 0 ? `eaten after ${(eatenAt / 60).toFixed(1)} s` : "still there after 15 s");

  // a click on the water makes a ripple and drops food
  for (let i = 0; i < 300; i++) P.step(dt);
  const foodBeforeClick = P.food.length;
  const probe = () => { let m = 0; for (let x = -9; x <= 9; x += 1.5) for (let z = -9; z <= 9; z += 1.5) if (x * x + z * z < 81) m = Math.max(m, Math.abs(P.waterHeight(x, z))); return m; };
  const quiet = probe();
  const rect = canvas.getBoundingClientRect();
  const cx = rect.left + rect.width / 2, cy = rect.top + rect.height * 0.55;
  const opt = { bubbles: true, cancelable: true, clientX: cx, clientY: cy, button: 0, buttons: 1, pointerId: 1, pointerType: "mouse", isPrimary: true };
  canvas.dispatchEvent(new PointerEvent("pointerdown", opt));
  canvas.dispatchEvent(new MouseEvent("mousedown", opt));
  canvas.dispatchEvent(new PointerEvent("pointerup", Object.assign({}, opt, { buttons: 0 })));
  canvas.dispatchEvent(new MouseEvent("mouseup", Object.assign({}, opt, { buttons: 0 })));
  canvas.dispatchEvent(new MouseEvent("click", Object.assign({}, opt, { buttons: 0 })));
  await sleep(100);
  P.step(dt);
  P.step(dt);
  const after = probe();
  ok("click_ripples_and_feeds", P.food.length > foodBeforeClick && after > quiet + 0.002,
    `food ${foodBeforeClick} -> ${P.food.length}, water ${quiet.toFixed(4)} -> ${after.toFixed(4)} m`);
  return R;
}
