---
name: motion-scroll-react
description: Build and debug scroll-linked and scroll-triggered animations in React, Next.js, and JavaScript using Motion, including useScroll, useTransform, useSpring, useInView, motion values, reduced-motion handling, parallax, progress indicators, sticky headers, and lightweight alternatives to GSAP. Use when Codex is asked for React scroll animations, Motion scroll hooks, parallax in React, viewport reveals, or performance-friendly scroll-linked UI.
---

# Motion Scroll React

## Core Approach

Use Motion for React-native animation ergonomics, layout animation, gestures, small-to-medium scroll effects, and composable motion values. Use GSAP ScrollTrigger instead when a page needs heavy scene choreography, pinning, Flip-style layout morphs across many elements, or timeline authoring.

Primary sources:
- GitHub: https://github.com/motiondivision/motion
- Docs: https://motion.dev/docs
- useScroll: https://motion.dev/docs/react-use-scroll

## Patterns

Page progress:
```jsx
import { motion, useScroll, useSpring } from "motion/react"

function ProgressBar() {
  const { scrollYProgress } = useScroll()
  const scaleX = useSpring(scrollYProgress, { stiffness: 120, damping: 24 })
  return <motion.div className="progress" style={{ scaleX }} />
}
```

Element parallax:
```jsx
function ParallaxCard() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"]
  })
  const y = useTransform(scrollYProgress, [0, 1], ["-12%", "12%"])
  const scale = useTransform(scrollYProgress, [0, 0.5, 1], [0.96, 1, 0.98])

  return <motion.article ref={ref} style={{ y, scale }}>...</motion.article>
}
```

Viewport reveal:
```jsx
<motion.section
  initial={{ opacity: 0, y: 32 }}
  whileInView={{ opacity: 1, y: 0 }}
  viewport={{ once: true, amount: 0.35 }}
  transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
/>
```

Sticky header direction:
```jsx
const { scrollY } = useScroll()
const [hidden, setHidden] = useState(false)

useMotionValueEvent(scrollY, "change", (current) => {
  const previous = scrollY.getPrevious() ?? current
  setHidden(current > previous && current > 120)
})
```

## Rules

- Keep scroll values as MotionValues; avoid calling React state setters every scroll tick unless reacting to coarse direction/state changes.
- Compose with `useTransform` and `useSpring` rather than manually computing styles in render.
- Prefer `whileInView` or `useInView` for one-shot reveals.
- Prefer `useScroll({ target, offset })` for scroll-linked parallax or progress.
- Animate compositor-friendly properties: transform, opacity, filter, clip-path.
- Use `useReducedMotion()` and provide non-motion states.
- In Next.js App Router, put Motion components in client components.

## Quality Bar

Check that:
- Hydration is clean and no browser-only APIs run in server components.
- Scroll animations do not trigger layout reflow each frame.
- Text and cards remain readable at mobile viewport widths.
- Motion values are not converted into React state on every scroll tick.
- Reduced-motion behavior is intentional.
- Screenshots show intermediate scroll states with no overlaps.
