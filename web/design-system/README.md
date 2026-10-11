# bult design system (draft v0.1)

**bult** (бұлт) is Kazakh for *cloud*. The brand is a clear daytime sky: flag blue at the top, a real cumulus photo, and warm gold light from a corner. The palette comes from the Kazakhstan flag. The landing page is airy and short on words. The dashboard is calm and quiet, and uses the same colors, fonts and radii at lower volume.

| File | What it is |
|---|---|
| `tokens.css` | CSS custom properties: scales, surfaces, text, borders, radius, spacing, shadows, type, motion. `:root` = light dashboard, `.bult-sky` = landing hero, `.bult-night` = dark surfaces (log viewer, terminal). |
| `mantine-theme.ts` | Mantine 8 `createTheme` with the same values: color tuples, fonts, radius, shadows, and component defaults. |
| `specimen.html` | One self-contained page with the hero, a three-item "Push, build, run" strip, foundations, two dashboard screens and a component sheet. |
| `screenshot-*.png` | Renders at 1440×900. |

## Palette

| Role | Hex | Use |
|---|---|---|
| Flag blue (`sky-5`) | `#00AFCA` | Sky, primary button fill **with navy text**, focus ring, active tab underline |
| Sky text (`sky-7`) | `#00788D` | Links and blue text on white (5.2:1) |
| Gold (`sun-5`) | `#FEC50C` | Landing CTA, the "building" dot, light on clouds. **Never text on white** (1.6:1) |
| Gold text (`sun-8`) | `#8A6500` | Text in the gold family, such as the "Building" badge (5.1:1 on `sun-0`) |
| Ink (`slate-9`) | `#0B1622` | Primary text, logo cloud |
| Secondary text (`slate-6`) | `#5B6B7B` | Meta, table headers (5.5:1 on white) |
| Page (`slate-0`) | `#F5F8FA` | Dashboard background. Cards are `#FFFFFF` |
| Night (`night-8`) | `#0A1826` | Log viewer and terminal surfaces |
| Success | `#0F7A55` on `#E7F6EF` | Running (4.8:1) |
| Danger | `#C4283C` on `#FFF0F1` | Failed, errors, destructive actions (5.1:1, and 5.7:1 on white) |

**Contrast rules (WCAG AA, computed):**
- Navy on flag blue = **6.9:1**, which passes. White on flag blue = **2.6:1**, which fails. Primary buttons are therefore flag blue with a navy label. `mantine-theme.ts` forces this through `Button` vars. `primaryShade` is 7, so the components Mantine colors itself (Anchor, Checkbox, Switch) stay accessible too.
- Gold carries meaning as a fill or a dot only: the CTA (navy on gold = 11.5:1), status dots, and step 3 of the strip. When text needs to read as gold, use `sun-8`.
- `slate-5 #7A8B9B` (3.5:1) is for placeholders and disabled states only.
- In the hero, navy text sits on the graded sky photo: at least 5.0:1 on the actual pixels behind the headline and buttons. On dark surfaces, text is `#E6EEF4` (15:1) and secondary text is `#B9C7D3` (10.4:1).
- Status badges never rely on color alone. Each one has a dot and a word.

## Type

- **Bricolage Grotesque** (700, optical size 96) is for **landing headlines only**. It is a grotesque with character: slightly soft ink traps and tight at large sizes (`-0.03em`). It reads as confident without shouting, which suits a calm sky brand better than compressed uppercase.
- **Onest** (400/500/600) is the face for all UI and body text. It has open, even shapes and stays clear at 13–14 px in dense tables. Dashboard headings use Onest 600, not the display face.
- **JetBrains Mono** (400/500) is for machine values only: SHAs, image digests, ports, IPs, URLs in tables, and logs. Its slashed zero matters for digests. Never use it for labels or headings.

Dashboard scale: 12 / 13 / 14 (body) / 16 / 20 / 24 (page title). Landing: a 96 px headline, 32 px step titles.

## Shape and depth

Radius grows with the size of the element: 6 px (badges), 8 px (buttons, inputs; the default), 12 px (cards, table, log viewer), 20 px (landing cards), pill (landing CTAs and the live-URL pill). Shadows are cool and tinted toward the sky. Dashboard cards get `xs` and toasts get `lg`. Only the landing uses the large `shadow-cloud` for floating objects.

## Sky photo (landing)

The hero background is a real photo, not drawn clouds: `assets/sky-hero.jpg` (2400x1600, 405 KB JPEG). It is a clear blue sky with a bank of white cumulus along the bottom, so it sits behind the copy without competing with it.

- **Placement:** `object-fit: cover`, anchored to the bottom (`object-position: 50% 100%`), so at 1440x900 the cloud bank fills the lower ~40% of the hero and the sky stays clear behind the headline.
- **Brand grade:** the photo's sky is deeper and more navy than flag blue and has a slight dark vignette. A CSS overlay (`.sky::after`) pulls the top toward `#00AFCA` (about 74% at the top, fading out by 80% of the height) and a haze at the very bottom blends the clouds into the next section (`#F4FCFE`). It still reads as a photograph. The warm top-right glow (`.glow`) stays; there is no drawn sun.
- **Contrast (measured on the rendered pixels behind the text, navy `#0B1622`):** headline 5.0:1 at its worst point (mean 5.8), buttons row 5.6:1, nav links 6.4:1, wordmark 4.7:1.
- **Motion:** one transform-only drift (scale 1.04 to 1.06 and translateX of 6 px, 80 s, alternate). No per-frame JS. Under `prefers-reduced-motion` it is static.
- **Story:** the commit tag flies from the terminal down into the cloud bank, and the Live pill rises out of it.
- **Performance:** one 405 KB request, with `<link rel="preload" as="image">` and `fetchpriority="high"` on the `<img>`. The page runs no script for the background.
- **In the real Next.js app:** use `next/image` (`fill`, `priority`, `sizes="100vw"`) so it ships AVIF/WebP with a width-based `srcset` (for example 828/1280/1920/2400 px) instead of the one JPEG. Keep the `object-position` and the overlay.
- **Limitations:** the cloud bank is anchored to the bottom, so on very wide/short viewports the cover crop trims the sky first, not the clouds. The tag and pill positions are tuned for 1440x900 and are absolute in the specimen.

## Credits

- Hero photo: "White cloud sky" by **Kumiko Shimizu** on Unsplash, https://unsplash.com/photos/white-cloud-sky-lNxMcE8mvIM. Licensed under the [Unsplash License](https://unsplash.com/license) (free to use, including commercially; attribution is not required but is given in the landing footer as "Photo: Kumiko Shimizu / Unsplash").

## Motion

**Landing (expressive, restrained):**
- **One** intro, about 3.5 s, played once after the fonts load: headline lines rise out of a mask, CTAs and terminal fade up, the terminal prints `git push`, a commit tag arcs down into the cloud bank, and a `https://blog.bult.localhost` Live pill rises out of it.
- Ambient: a very slow drift of the sky photo (transform only).
- Only `transform` and `opacity` animate. Nothing is tied to scroll.
- Under `prefers-reduced-motion: reduce`: no drift, no intro. The photo is static and every element is in its final state (checked: zero running animations).

**Dashboard (functional only):**
- Hover and press 120 ms, state changes 180 ms, panels 320 ms (`--ease-standard`).
- The only loops are the pulsing dot on in-progress statuses and button spinners. Both stop under reduced motion.
- No entrance animations, no hover lift.

## Do / don't

**Do**
- Keep copy short. Labels and data only. One headline, two buttons, three steps.
- Use flag blue as a fill with navy text, and `sky-7` for blue text.
- Keep gold as an accent: the landing primary button, the "building" dot, light on cloud tops.
- Put machine values in mono and everything people read in Onest.
- Write status as a dot plus a word.

**Don't**
- Don't put white text on flag blue or gold text on white.
- Don't use Bricolage or gradients inside the dashboard.
- Don't draw a sun, add more clouds, or add motion to the hero. Its one story is push, cloud, live URL.
- Don't animate layout properties or loop anything idle in the app UI.
- Don't use the flag's eagle or ornament.

## Wiring notes (Next.js 16 + Mantine 8)

- Load the fonts with `next/font/google` (`Bricolage_Grotesque` with `axes: ["opsz"]`, `Onest`, `JetBrains_Mono`). Expose them as `--font-display`, `--font-sans` and `--font-mono` on `<html>`. `tokens.css` and the theme read these variables.
- Import `tokens.css` once in `app/layout.tsx`, after `@mantine/core/styles.css`.
- Map statuses to colors with `deployStatusColor` from `mantine-theme.ts`, for example `<Badge color={deployStatusColor[s]}>`.
- Draft limitations: the sidebar was designed only at ≥ 1280 px. There is no dashboard dark mode yet, although the `dark` tuple (night) is ready. The icons in the specimen are hand-drawn approximations of Tabler icons, so use `@tabler/icons-react` in the app.
