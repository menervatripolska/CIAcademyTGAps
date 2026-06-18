---
name: scrollama-scrollytelling
description: Build scrollytelling, sticky narrative sections, step-triggered graphics, editorial data stories, and scroll-progress interactions using Scrollama, IntersectionObserver, CSS sticky positioning, D3/Mapbox/canvas integrations, and performance-safe step callbacks. Use when Codex is asked for narrative scroll stories, sticky graphics with text steps, scroll-driven charts/maps, article interactives, or replacing brittle scroll event code.
---

# Scrollama Scrollytelling

## Core Approach

Use Scrollama when content advances through narrative steps and each step triggers a state change in a sticky visual. It is not a smooth scrolling library and not a choreographed animation timeline; combine it with D3, Mapbox, canvas, GSAP, or Motion for visuals.

Primary sources:
- GitHub: https://github.com/russellsamora/scrollama
- Demos: https://russellsamora.github.io/scrollama/

## Page Structure

Use native CSS sticky for the visual and Scrollama for step enter/exit/progress.

```html
<section class="story">
  <figure class="graphic" aria-hidden="true"></figure>
  <div class="steps">
    <article class="step" data-step="intro"></article>
    <article class="step" data-step="contrast"></article>
    <article class="step" data-step="result"></article>
  </div>
</section>
```

```css
.story {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(18rem, 34rem);
  gap: 4rem;
}

.graphic {
  position: sticky;
  top: 0;
  height: 100svh;
}

.step {
  min-height: 80svh;
}
```

## Setup

```js
import scrollama from "scrollama"

const scroller = scrollama()

scroller
  .setup({
    step: ".step",
    offset: 0.55,
    progress: true
  })
  .onStepEnter(({ element, index, direction }) => {
    updateGraphic(element.dataset.step, { index, direction })
  })
  .onStepProgress(({ element, progress }) => {
    updateProgress(element.dataset.step, progress)
  })
  .onStepExit(({ element, direction }) => {
    element.classList.toggle("is-active", direction === "up")
  })
```

## Rules

- Keep step callbacks cheap. Set state or call prepared render functions; do not query layout repeatedly.
- Use `progress: true` only where continuous progress is needed.
- Use `ResizeObserver` or Scrollama resize handling when content dimensions change.
- Avoid viewport-height bugs on mobile; prefer `svh/dvh` and test address-bar behavior.
- Do not rely on `vh` alone for mobile scrollytelling.
- Provide normal article content order so the story works without JavaScript.
- For charts/maps, preload data and render stable base states before scrolling begins.

## Mobile

For narrow screens, prefer an overlay pattern or stack each visual near its text. A side-by-side sticky graphic often fails on mobile. Use shorter step heights and reduce continuous scrubbing.

## Quality Bar

- The story reads in source order.
- Sticky graphic does not obscure text.
- Step changes are legible while scrolling slowly and quickly.
- Keyboard/touch users can progress naturally.
- Visual state is deterministic when scrolling upward.
