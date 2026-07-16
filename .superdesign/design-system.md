# Hunt Board landing page design system

Style foundation: Superdesign's `mosaic-grid-architecture-style`, adapted to the supplied safari prototype and Hunt Board's ingestion pipeline. Preserve its technical blueprint discipline, flat wireframe construction, forest-on-paper contrast, and monospaced metadata. Replace its generic bento and orbit motifs with route plotting, source coordinates, dedupe intersections, and a sightings ledger.

## Product context

Hunt Board is a backend-first, single-user job intelligence system. It pulls listings from curated ATS sources, normalizes and deduplicates them, ranks title matches, and tracks source health. The landing page has one job: make a technically minded job seeker understand that the product turns scattered listings into a focused daily route, then invite them to preview the static product concept.

The public-facing product and website name is **Hunt Board**. A small utility annotation such as `Job-search field desk` may accompany the Hunt Board wordmark.

## Visual thesis

Treat job search as a modern safari field expedition: purposeful observation, route planning, and careful cataloging rather than safari tourism or novelty decoration. The page should feel like a survey map and naturalist field kit laid on a precise worktable, with useful coordinates, plotted routes, source sightings, compact field annotations, and a restrained savannah horizon. Avoid animals, photographic stock art, faux-vintage distressing, generic SaaS gradients, floating glass cards, and decorative dashboard statistics.

The signature element is a large **route map** in the hero: a plotted path from multiple ATS source marks through normalize, dedupe, rank, and shortlist waypoints. It should read immediately as both a map and a truthful diagram of the product.

The supporting signature is an original, code-native safari illustration system using flat inline SVG silhouettes: acacia canopies, layered grass, a compact camera, and binoculars. Keep every illustration within the existing paper, forest, graphite, olive, orange, and yellow palette. The illustrations must frame product content rather than replace it.

## Color tokens

- `survey-paper` — `#F2EBD9`: primary page surface
- `paper-light` — `#FBF8EF`: elevated cards and route labels
- `forest-ink` — `#163D34`: primary text, navigation, dark panels
- `graphite` — `#252821`: body text and fine rules
- `signal-orange` — `#E4572E`: primary actions, active route, fresh listing markers
- `grid-olive` — `#8B9274`: map grid, muted labels, secondary borders
- `sun-yellow` — `#F2C14E`: sparing highlight for ranking and freshness

Use flat color and ink-like line work. No gradients. Orange is the only action color and should occupy less than 10% of the page.

## Typography

- Display: `Barlow Condensed`, weights 600–700. Use for the hero and short section headings; tight leading, never for paragraphs.
- Body: `Manrope`, weights 400–600. Use for navigation, descriptions, and controls.
- Utility/data: `IBM Plex Mono`, weights 400–500. Use for coordinates, source names, timestamps, ranks, and diagram labels.

Headlines use sentence case rather than all caps. Utility labels may use uppercase with `0.08em` tracking.

## Scale and spacing

- Content maximum: `1280px`
- Outer gutter: `24px` mobile, `40px` tablet, `64px` desktop
- Spacing base: `4px`; common steps `8, 12, 16, 24, 32, 48, 72, 96`
- Hero headline: `clamp(3.5rem, 7vw, 7.5rem)` with `0.86` line-height
- Section heading: `clamp(2rem, 4vw, 4.25rem)`
- Body: `16–18px`, `1.6` line-height
- Corners: mostly `0–8px`; avoid pill-shaped containers except tiny status tags

## Layout

- Full-width page with a disciplined 12-column desktop grid.
- Sticky, compact top navigation on paper with a thin forest rule.
- Hero is an asymmetric split: oversized thesis and actions on the left; route-map instrument panel on the right, with the headline allowed to overlap the map boundary slightly on wide screens.
- Follow with a narrow source ticker, a three-part capability narrative, a sample sightings ledger, then one decisive closing call-to-action.
- Mobile stacks all regions, preserves the map, converts table-like rows into readable cards, and keeps touch targets at least 44px.

## Components

### Wordmark

Simple inline compass/survey mark plus `HUNT BOARD` wordmark and small `Job-search field desk` annotation. Use inline SVG; do not depend on image assets.

### Buttons

- Primary: signal orange fill, forest ink or paper text based on contrast, 2px graphite shadow-offset, square-ish corners, clear hover translation.
- Secondary: transparent paper, 1px forest border, no rounded pill treatment.
- Focus: 3px sun-yellow outline with 3px offset.

### Route map

Paper-light panel with olive coordinate grid, minimal contour lines, ATS source labels, a bold orange route, and four explicit system waypoints: Collect, Normalize, Rank, Shortlist. Include a compact legend. This is a conceptual static visualization, not a functional map.

### Source ticker

Single horizontal band of ATS names and truthful product actions: Greenhouse, Lever, Ashby, normalize, dedupe, rank. Avoid fake customer-logo claims.

### Capability modules

Use structural diagrams and concise copy rather than icon cards. The sequence is meaningful: Watch sources → Resolve duplicates → Surface the best matches.

### Sightings ledger

A static set of plausible sample roles presented as a camera film strip: a graphite or forest film body, repeated square sprocket holes, and paper-light listing frames. Show source, title/company, work type/location, freshness, and match score. Clearly label data as a product preview/sample and preserve readable responsive behavior.

### Safari horizon and field tools

- Build the acacia trees, grass layers, camera, and binoculars as original inline SVG or CSS shapes; do not copy or embed third-party Google images.
- Use a low grass silhouette and two or three acacia forms as a horizon band around the hero route map, never behind body copy.
- Use camera and binocular illustrations as small section markers or hover targets. They may tilt, focus, or shift slightly, but must not imply a working control.
- Do not introduce new greens, sky blue, animal imagery, or cartoon outlines outside the established technical line-art style.

## Motion

- One orchestrated page-load sequence: the orange route draws across the map, then the route labels fade in.
- A subtle breeze may rustle grass blades and move acacia canopies; pause or strengthen it only on hover.
- Camera and binocular line illustrations may tilt, focus, or nudge on hover; keep movement within 2–4 degrees or 4–8 pixels.
- Small button offset and film-frame highlight on hover.
- Subtle section reveal only if it does not distract from the route animation.
- Respect `prefers-reduced-motion`; show all content immediately and disable route drawing.

## Accessibility and content rules

- WCAG-aware contrast, visible focus, semantic landmarks, and descriptive labels.
- Do not claim live data, current listing counts, customer adoption, or working accounts.
- Calls to action should describe static outcomes: `Explore the concept` and `See how it works`.
- State plainly that the page is a preview where needed.
- The static implementation may use anchor navigation and presentational controls only; no API calls or forms that imply submission.
