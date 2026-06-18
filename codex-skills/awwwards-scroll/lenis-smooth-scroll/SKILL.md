---
name: lenis-smooth-scroll
description: Add, tune, and debug Lenis smooth scrolling for high-end websites, including GSAP ScrollTrigger integration, scroll syncing with WebGL/canvas, parallax, anchors, nested scroll areas, accessibility, and mobile fallbacks. Use when Codex is asked for smooth scroll, inertial scroll, Awwwards-style scrolling, Lenis setup, scroll performance, or conflicts between smooth scrolling, fixed elements, iframes, modals, anchors, or ScrollTrigger.
---

# Lenis Smooth Scroll

## Core Approach

Use Lenis as the scroll transport layer, not as the whole animation system. Pair it with GSAP ScrollTrigger, Motion, or WebGL logic when the page needs choreographed animation. Keep native scroll behavior when the design does not benefit from smooth/inertial scrolling.

Primary sources:
- GitHub: https://github.com/darkroomengineering/lenis
- Docs/showcase: https://www.lenis.dev/
- Package: https://www.npmjs.com/package/lenis

## Setup

Use one RAF owner. Do not run multiple independent RAF loops that fight each other.

Standalone:
```js
import Lenis from "lenis"

const lenis = new Lenis({
  autoRaf: true,
  anchors: true
})
```

GSAP ScrollTrigger:
```js
import Lenis from "lenis"
import gsap from "gsap"
import { ScrollTrigger } from "gsap/ScrollTrigger"

gsap.registerPlugin(ScrollTrigger)

const lenis = new Lenis({ autoRaf: false, anchors: true })

lenis.on("scroll", ScrollTrigger.update)

gsap.ticker.add((time) => {
  lenis.raf(time * 1000)
})

gsap.ticker.lagSmoothing(0)
```

## Implementation Rules

- Include Lenis recommended CSS from the current docs or package examples.
- Enable anchors intentionally with `anchors: true` or configured offsets.
- Stop Lenis for blocking modals, command palettes, and full-screen overlays; restart it on close.
- Mark nested/native scroll areas with the relevant `data-lenis-prevent*` attributes.
- Avoid smooth scrolling inside iframes; wheel events usually do not forward reliably.
- Treat mobile separately. Disable, reduce, or simplify smooth scrolling when touch behavior feels laggy.
- Always test Safari and iOS behavior when possible.

## Debug Checklist

- Page is actually scrollable without Lenis.
- Only one Lenis instance exists.
- RAF is called exactly once per frame.
- ScrollTrigger is refreshed after image/font/layout changes.
- Fixed/sticky elements are not inside transformed wrappers that break expected positioning.
- Smooth scroll is disabled or guarded for `prefers-reduced-motion`.
- Nested scroll containers declare prevention attributes.

## Awwwards Patterns

Use Lenis to make these feel continuous:
- DOM parallax layers that move at slightly different rates.
- WebGL planes tracking DOM images.
- Scroll-scrubbed typography and masked image reveals.
- Momentum-sensitive headers or cursor details.
- Horizontal galleries driven by vertical scroll.

Keep Lenis invisible to users: the interaction should feel expensive, not slippery.
