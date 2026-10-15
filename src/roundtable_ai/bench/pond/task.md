Build a living 3D koi pond in the browser with three.js: real water waves, schooling fish, food and lily pads, in `index.html` (you may add `.js` and `.css` files next to it). It must look good and behave physically; hidden checks run it in a headless browser and a person will look at it. No build step: open `index.html` and it runs.

## Setup

- Use three.js 0.170.0 as an ES module from `https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js` (with an import map), and its addons from `https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/` (for example `controls/OrbitControls.js`). No other libraries.
- The canvas fills the window and follows resizes. The camera can be orbited and zoomed with the mouse.
- Units are metres. The pond is round: radius **10**, depth **3**. The still water surface is at **y = 0**; the bottom is at y = -3.

## The water

- The surface is a height field simulated with the wave equation (or an equivalent damped spring grid) on at least 96 x 96 cells: a disturbance spreads outward as rings, reflects from the pond's edge, and dies away within about 15 seconds.
- Clicking the water makes a ripple where you clicked and drops a food pellet there.
- A fish swimming within 0.3 m of the surface disturbs it slightly.
- The water is shaded like water (transparent, with specular highlights from the waves' normals), over a visible bottom (sand, stones) and a stone rim.

## The fish

- At least **15** koi with real bodies (a tapered body, fins and a tail; colourful koi patterns), each pointing where it swims, its tail swinging faster when it swims faster.
- They move as a school (boids): they keep apart from close neighbours (separation), steer toward the average heading of nearby fish (alignment) and toward their centre (cohesion), with a limited speed (between 0.3 and 4 m/s) and a limited turning rate.
- They stay inside the pond: never closer than 0.3 m to the wall, the bottom or the surface, turning away smoothly rather than bouncing.

## Food

- A pellet floats for a moment, then sinks slowly to the bottom.
- Fish within 6 m of a pellet swim to it; the first to reach it (its head within 0.4 m) eats it and the pellet disappears. Fish swim faster while chasing food.

## Lily pads

- At least 4 lily pads float on the surface and ride the waves: each one's height follows the water height under its centre.

## Test interface (required)

`window.pond` must exist once the page has loaded, with:

| Member | Meaning |
| --- | --- |
| `bounds` | `{ radius: 10, depth: 3 }` |
| `fish` | array, one object per fish, each with `position` and `velocity` objects that have numeric `x`, `y`, `z` (live values) |
| `food` | array of the pellets still in the water, each with a `position` `{x, y, z}` |
| `lilyPads` | array, each with a `position` `{x, y, z}` (y follows the water) |
| `paused` | `false` while the page animates itself; when a test sets it to `true`, the automatic simulation stops (rendering may go on) |
| `step(dt)` | advances the whole simulation (water, fish, food, lily pads) by `dt` seconds, also while paused |
| `addRipple(x, z, strength)` | disturbs the water at (x, z); strength 1 is a pebble dropping in |
| `dropFood(x, z)` | drops a pellet at (x, z) |
| `waterHeight(x, z)` | the current surface height at (x, z) (0 when still) |

Tests call `step(1/60)` many times in a row; one second of simulation must take well under a second to compute.
