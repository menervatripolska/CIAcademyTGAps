---
name: r3f-scroll-webgl
description: Build, refactor, and verify scroll-synced WebGL and 3D website experiences with React Three Fiber, Drei, Three.js, Lenis, and r3f-scroll-rig. Use when Codex is asked for Awwwards-style 3D scroll scenes, WebGL image planes, DOM-to-canvas synchronization, scroll-driven cameras, shader uniforms, GLB models, postprocessing, or frontend pages mixing HTML content with a persistent Three.js canvas.
---

# R3F Scroll WebGL

## Core Approach

Use React Three Fiber when 3D/WebGL is part of the primary experience. Keep one persistent canvas whenever possible. Use DOM for layout and accessibility, then sync WebGL objects to DOM positions instead of rebuilding the whole page as canvas UI.

Primary sources:
- React Three Fiber: https://github.com/pmndrs/react-three-fiber
- Drei: https://github.com/pmndrs/drei
- r3f-scroll-rig: https://github.com/14islands/r3f-scroll-rig
- Three.js: https://threejs.org/docs/

## Architecture

Choose one of three patterns:

1. Simple 3D section: a single `<Canvas>` inside the section, useful for isolated hero/feature moments.
2. Persistent canvas: one global R3F canvas behind/above DOM, useful for page-wide transitions and scroll continuity.
3. r3f-scroll-rig: track DOM proxy elements and render matching WebGL meshes, useful for image planes, GLB objects attached to HTML, and Awwwards-style DOM/WebGL hybrids.

## r3f-scroll-rig Pattern

```jsx
import { GlobalCanvas, SmoothScrollbar, UseCanvas, ScrollScene } from "@14islands/r3f-scroll-rig"

function AppLayout({ children }) {
  return (
    <>
      <GlobalCanvas />
      <SmoothScrollbar />
      {children}
    </>
  )
}

function TrackedMedia() {
  const el = useRef(null)
  return (
    <>
      <div ref={el} className="media-proxy" />
      <UseCanvas>
        <ScrollScene track={el}>
          {(props) => (
            <mesh {...props}>
              <planeGeometry />
              <meshBasicMaterial color="#1fd1a5" toneMapping={false} />
            </mesh>
          )}
        </ScrollScene>
      </UseCanvas>
    </>
  )
}
```

## Scroll-Driven Effects

- Drive shader uniforms from scroll progress.
- Move camera on scroll only when it supports the narrative; avoid constant arbitrary camera drift.
- Use `useFrame` for animation and read current scroll state from a single source.
- Use Drei for loaders, environments, images, shader helpers, and scroll utilities where appropriate.
- Use compressed assets: Draco/Meshopt GLB, KTX2/Basis textures, optimized image sizes.
- Reserve aspect ratios in DOM proxies to prevent cumulative layout shift.

## Performance Rules

- Use one canvas, not many canvases, for complex pages.
- Limit postprocessing passes. Treat bloom, DOF, RGB shift, and noise as expensive.
- Keep geometry and material counts low.
- Use `frameloop="demand"` only for mostly static scenes; keep default loop for active scroll/interaction scenes.
- Dispose resources or let R3F manage lifecycle through components.
- Degrade on mobile: fewer effects, lower DPR, simpler shaders, no heavy smooth scroll if touch feels bad.
- Respect reduced motion by freezing camera travel and replacing scroll-scrub effects with static states.

## Verification

Before finishing:
- Open the local site in a browser.
- Capture desktop and mobile screenshots.
- Confirm the canvas is nonblank and correctly framed.
- Scroll through the whole page and inspect at least one mid-scroll state.
- Check no DOM text overlaps the canvas or becomes unreadable.
- Check the page remains keyboard navigable and content remains present in DOM.
