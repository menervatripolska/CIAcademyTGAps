---
name: barba-page-transitions
description: Create and debug fluid animated page transitions with Barba.js, GSAP, Lenis, and route lifecycle cleanup. Use when Codex is asked for SPA-like transitions on multi-page sites, animated navigation, page enter/leave motion, preserving smooth scroll across pages, killing scroll triggers on route changes, or adapting Awwwards-style page transition concepts.
---

# Barba Page Transitions

## Core Approach

Use Barba when the site is multi-page but should feel continuous. Keep transition logic separate from page-specific animation setup. Always clean up page effects before Barba replaces containers.

Primary sources:
- GitHub: https://github.com/barbajs/barba
- Docs: https://barba.js.org/
- GSAP: https://github.com/greensock/GSAP
- Lenis: https://github.com/darkroomengineering/lenis

## Lifecycle Rules

1. Before leave: stop navigation spam, freeze or stop smooth scrolling, and kill page-local animation side effects.
2. Leave: animate old container out.
3. Before enter: reset scroll position, prepare next container initial styles, reinitialize page modules.
4. Enter: animate new container in.
5. After enter: restart smooth scroll, refresh ScrollTrigger, restore focus to meaningful content.

## Pattern

```js
import barba from "@barba/core"
import gsap from "gsap"
import { ScrollTrigger } from "gsap/ScrollTrigger"

gsap.registerPlugin(ScrollTrigger)

function cleanupPage() {
  ScrollTrigger.getAll().forEach((trigger) => trigger.kill())
}

function initPage() {
  // page-local scroll triggers, interactions, media setup
  ScrollTrigger.refresh()
}

barba.init({
  transitions: [{
    name: "fade-slide",
    async leave({ current }) {
      cleanupPage()
      await gsap.to(current.container, {
        opacity: 0,
        y: -32,
        duration: 0.45,
        ease: "power2.inOut"
      })
    },
    beforeEnter({ next }) {
      window.scrollTo(0, 0)
      gsap.set(next.container, { opacity: 0, y: 32 })
    },
    async enter({ next }) {
      initPage()
      await gsap.to(next.container, {
        opacity: 1,
        y: 0,
        duration: 0.65,
        ease: "power3.out"
      })
    }
  }]
})
```

## Design Patterns

- Mask wipe: a full-screen overlay reveals the next page with clip-path or transform.
- Kinetic title handoff: use the clicked project title as transition material, then settle into the detail hero.
- Image continuity: clone the clicked thumbnail, animate it to the next page hero bounds, then swap to real content.
- Menu transition: animate nav out, route, then animate nav context back in.
- Background color morph: transition page theme variables during leave/enter.

## Quality Bar

- Links still work with browser back/forward.
- Focus and scroll position are intentional after each transition.
- Analytics/pageview hooks are updated if the app uses analytics.
- ScrollTrigger, Lenis, media listeners, and custom observers do not leak across pages.
- Reduced-motion users get a fast non-flashy transition.
- Content is not hidden if JavaScript fails.
