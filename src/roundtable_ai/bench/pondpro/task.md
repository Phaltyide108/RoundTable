Build a physically accurate 3D koi pond in the browser with three.js, in `index.html` (you may add `.js` and `.css` files next to it). Hidden checks measure the physics against the numbers below, with 200 fish as well as 18, and a person will look at it. No build step: serve the folder and open `index.html`.

## Setup

- three.js 0.170.0 as an ES module from `https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js` (import map), addons from `https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/`. No other libraries.
- The canvas fills the window and follows resizes; orbit and zoom with the mouse.
- Metres and seconds. Round pond: radius **10**, depth **3**; still water at **y = 0**, bottom at y = -3.

## Water (a damped wave equation on a height field, at least 96 x 96 cells)

- Waves travel at **2.0 m/s** (a ripple's crest reaches 4 m from where it started after about 2 s).
- Without new disturbances, wave amplitude **halves every 3 s**.
- Waves reflect from the pond's edge; no energy leaks out of the pond and none is created: the simulation stays stable (no growing or exploding waves, no NaN) whatever happens, including many strong ripples at once.
- `addRipple(x, z, strength)`: strength 1 is a pebble dropping in (a dip about 10 cm deep and 1 m wide).
- Clicking the water makes a ripple there and drops a pellet there.

## Fish

- 18 koi by default, with real bodies (tapered body, fins, tail, koi colours), pointing where they swim, the tail beating faster when they swim faster.
- They school (boids): separation (no two fish ever closer than **0.4 m**, centre to centre), alignment, cohesion.
- Speed between **0.2 and 2.0 m/s**; turning no faster than **3 rad/s**.
- They stay at least **0.3 m** from the wall, the bottom and the surface, and outside every stone (at least 0.2 m from its surface).
- `setFishCount(n)` replaces the school with n fish; with **200** fish one simulated second must take under 0.6 s to compute, and the page must still render smoothly (find neighbours with a grid or similar, not by checking every pair).

## Stones

- At least 5 stones on the bottom, each a sphere-like rock with radius 0.4 to 1.0 m, in `stones` as `{ position, radius }`. Fish swim around them.

## The heron

- `setHeron(x, z)` puts a heron standing in the water at (x, z); `setHeron(null)` takes it away. `heron` is `null` or `{ position: {x, y, z} }`.
- Fish within **4 m** of the heron (horizontally) flee from it while it is there, faster than they ever swim otherwise: above 2.0 m/s, at most **3.0 m/s**.

## Food

- A pellet floats on the surface for **2 s**, then sinks at a steady **0.25 m/s** until it rests on the bottom.
- Fish within 6 m swim to the nearest pellet; a fish whose head comes within 0.35 m of a pellet eats it and it disappears.

## Lily pads

- At least 4 lily pads ride the waves: each one's height follows the water height under its centre.

## Determinism

- `reset(seed)` rebuilds the pond's 18 fish, stones and pads from an integer seed and calms the water and removes food and the heron (use your own seeded random generator): the same seed followed by the same `step` calls gives exactly the same positions.

## Test interface (required)

`window.pond` must exist once the page has loaded:

| Member | Meaning |
| --- | --- |
| `bounds` | `{ radius: 10, depth: 3 }` |
| `fish` | array, each with live `position` and `velocity` (`x`, `y`, `z` numbers) |
| `food` | array of pellets still in the water, each with a `position` |
| `lilyPads` | array, each with a `position` (y follows the water) |
| `stones` | array of `{ position, radius }` |
| `heron` | `null` or `{ position }` |
| `paused` | `false` while the page animates itself; `true` stops the automatic simulation |
| `step(dt)` | advances everything by dt seconds, also while paused |
| `addRipple(x, z, strength)`, `dropFood(x, z)`, `waterHeight(x, z)` | as above |
| `setFishCount(n)`, `setHeron(x, z)` / `setHeron(null)`, `reset(seed)` | as above |
