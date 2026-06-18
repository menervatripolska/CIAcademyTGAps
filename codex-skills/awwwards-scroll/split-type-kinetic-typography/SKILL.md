---
name: split-type-kinetic-typography
description: Create kinetic typography, split-text reveals, staggered characters, masked headline motion, and scroll-driven text animation using SplitType, GSAP SplitText, Splitting.js, GSAP, Motion, CSS, and accessibility-safe text handling. Use when Codex is asked for animated typography, word/char/line reveals, Awwwards-style type motion, editorial scroll text, or fixing split-text layout/accessibility issues.
---

# Split Type Kinetic Typography

## Core Approach

Split text only when per-line, per-word, or per-character motion is essential. Preserve semantic text, avoid layout jumps, and always provide cleanup in component frameworks.

Primary sources:
- SplitType: https://github.com/lukePeavey/SplitType
- Splitting.js: https://github.com/shshaw/Splitting
- GSAP SplitText: https://gsap.com/docs/v3/Plugins/SplitText/
- Codrops typography inspiration: https://github.com/codrops/OnScrollTypographyAnimations

## SplitType Pattern

```js
import SplitType from "split-type"
import gsap from "gsap"
import { ScrollTrigger } from "gsap/ScrollTrigger"

gsap.registerPlugin(ScrollTrigger)

const split = new SplitType("[data-split]", {
  types: "lines, words",
  lineClass: "line",
  wordClass: "word"
})

gsap.from(split.words, {
  yPercent: 110,
  opacity: 0,
  stagger: 0.035,
  duration: 0.8,
  ease: "power3.out",
  scrollTrigger: {
    trigger: "[data-split]",
    start: "top 75%"
  }
})
```

CSS wrapper:
```css
[data-split] {
  font-kerning: none;
}

.line {
  overflow: hidden;
}

.word,
.char {
  display: inline-block;
}
```

## Rules

- Prefer splitting by lines/words for readable editorial motion. Use chars sparingly for logos, short labels, or expressive moments.
- Use `font-kerning: none` to reduce shift when splitting/reverting.
- Set stable widths when split text is inside flex/grid containers.
- Re-split after container width changes when line-based splitting is used.
- Revert split text on unmount, route change, or when the animation is no longer needed.
- Avoid splitting long paragraphs into chars; it is heavy and often unpleasant to read.
- Keep original semantic hierarchy: do not replace headings with visual-only spans.
- Respect reduced motion with non-split or instant visible states.

## Awwwards Patterns

- Masked line reveal: each line clips its words from below.
- Scroll scrub headline: words shift, blur, or fade based on section progress.
- Kinetic page transition: project title splits and expands into next view.
- Editorial cascade: paragraphs reveal by line as images slide independently.
- Character wave: short display words stagger in a curve, then settle quickly.

## Accessibility Checks

- The text remains selectable or at least present in DOM as real text.
- Screen readers do not announce every character separately because of careless `aria` changes.
- Motion does not delay access to essential content.
- The layout does not jump after webfonts load.
