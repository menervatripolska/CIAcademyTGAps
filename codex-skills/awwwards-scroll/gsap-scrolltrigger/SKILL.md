---
name: gsap-scrolltrigger
description: Create, refactor, and debug premium scroll-driven web animations with GSAP ScrollTrigger, ScrollSmoother, Flip, matchMedia, pinned timelines, scrubbed progress, parallax, SVG/canvas/WebGL sync, and Awwwards-style interaction choreography. Use when Codex is asked to build or improve scroll animations, pinned sections, scroll-scrubbed timelines, layout morphs, immersive landing pages, or animation performance in JavaScript, React, Next.js, Vue, or vanilla frontend code.
---

# GSAP ScrollTrigger

## Core Approach

Use GSAP when the experience needs deliberate choreography, sequence control, or reliable cross-browser behavior. Prefer native CSS/IntersectionObserver for simple one-shot reveals; reach for ScrollTrigger when scroll position must drive exact progress, pin sections, scrub timelines, coordinate many elements, or sync DOM with canvas/WebGL.

Primary sources:
- GitHub: https://github.com/greensock/GSAP
- Docs: https://gsap.com/docs/v3/Plugins/ScrollTrigger/
- ScrollSmoother: https://gsap.com/docs/v3/Plugins/ScrollSmoother/
- Flip: https://gsap.com/docs/v3/Plugins/Flip/

## Build Workflow

1. Map the page into scenes before writing code: trigger element, start/end positions, pinned duration, scrub behavior, animated properties, and teardown needs.
2. Animate only transform, opacity, clip-path, filter, SVG attributes, canvas uniforms, or cheap custom properties unless a specific layout animation is required.
3. Create timelines outside scroll callbacks and attach them to ScrollTrigger. Avoid manual scroll listeners for animation progress.
4. Use `markers: true` while developing, then remove markers before shipping.
5. Add responsive variants with `gsap.matchMedia()` instead of branching inside every animation.
6. Respect `prefers-reduced-motion`: disable scrub-heavy/pinned scenes or replace with simple state changes.
7. On React/Next.js, use `@gsap/react` and `useGSAP()` for scoped selectors and cleanup.
8. When using smooth scrolling, integrate the scroller with ScrollTrigger explicitly, and call `ScrollTrigger.refresh()` after images/fonts/layout changes.

## Patterns

Pinned story section:
```js
const tl = gsap.timeline({
  scrollTrigger: {
    trigger: section,
    start: "top top",
    end: "+=250%",
    scrub: 1,
    pin: true,
    anticipatePin: 1
  }
})

tl.from(title, { yPercent: 60, opacity: 0 })
  .to(media, { scale: 1.12, clipPath: "inset(0% 0% 0% 0%)" }, 0)
  .from(items, { y: 48, opacity: 0, stagger: 0.08 }, 0.25)
```

Responsive setup:
```js
const mm = gsap.matchMedia()

mm.add("(min-width: 900px)", () => {
  const ctx = gsap.context(() => {
    // desktop scroll scenes
  })
  return () => ctx.revert()
})

mm.add("(prefers-reduced-motion: reduce)", () => {
  ScrollTrigger.getAll().forEach((trigger) => trigger.disable())
})
```

React setup:
```jsx
import gsap from "gsap"
import { ScrollTrigger } from "gsap/ScrollTrigger"
import { useGSAP } from "@gsap/react"

gsap.registerPlugin(ScrollTrigger, useGSAP)

function Scene() {
  const scope = useRef(null)

  useGSAP(() => {
    gsap.from("[data-reveal]", {
      y: 32,
      opacity: 0,
      stagger: 0.06,
      scrollTrigger: {
        trigger: scope.current,
        start: "top 70%"
      }
    })
  }, { scope })

  return <section ref={scope}>...</section>
}
```

## Integration Checks

- If using Lenis, connect Lenis scroll events to `ScrollTrigger.update` and drive Lenis through the GSAP ticker or a single shared RAF loop.
- If animating layout changes, prefer Flip over measuring positions manually.
- For route transitions, kill or revert triggers before replacing page content.
- For WebGL, feed scroll progress into uniforms/camera values from `onUpdate`, not from independent scroll listeners.
- For image-heavy scenes, reserve stable dimensions and refresh after assets load.

## Quality Bar

Before finishing frontend work, verify:
- No animation changes layout unexpectedly during scroll.
- Pinned sections release at correct points on desktop and mobile.
- The browser remains responsive during fast wheel/touch scrolling.
- Reduced-motion users get a simpler experience.
- All triggers are cleaned up on component unmount or page transition.
- Visual screenshots show the animation target is nonblank, correctly framed, and not overlapping content.
