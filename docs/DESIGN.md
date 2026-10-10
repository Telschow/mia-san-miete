# Design system

The dashboard looks like a housing ledger, not a SaaS template: editorial type, hairline rules
instead of boxed cards, tinted neutrals, one accent per theme, no shadows, no gradients. Tokens
live in `src/mia_san_miete/gui/static/app.css`; this file says why, so changes stay coherent.
It follows the nine-section layout used by DESIGN.md collections such as
[awesome-design-md](https://github.com/VoltAgent/awesome-design-md), but describes only this
product (no brand is imitated).

## 1. Visual theme and atmosphere

Calm, dense, trustworthy: a register where numbers matter. Density is compact (a working tool
checked many times a day), motion is nearly absent, variance is low (a regular grid, with one
asymmetric overview). The personality comes from type and one regional motif (the Bavarian
lozenge), not from decoration.

## 2. Color palette and roles

Roles, not hues: `bg` page, `paper` inputs and queue cards, `paper-2` inset areas, `rule` hairline,
`rule-strong` section rule, `ink` text, `ink-2` secondary, `ink-3` hints, `accent`, `accent-ink`
(text on accent), `alert`. Neutrals are tinted toward the theme hue; there is no pure gray, and
only the High contrast theme uses pure black and white.

| Theme | Page | Ink | Accent | Notes |
|---|---|---|---|---|
| Paper (default light) | `#f3eee4` warm paper | `#221e18` | `#1d6a58` verdigris | |
| Slate (default dark) | `#15171b` | `#ece8e0` | `#e3a93f` amber | |
| Weiß-Blau (Bavarian) | `#f7f6f1` | `#0e2036` | `#0a67a8` | lozenge band `#0098d4` on white |
| Bayern Nacht | `#091a2d` | `#edf3f9` | `#52b6ea` | lozenge band on deep blue |
| High contrast | `#ffffff` | `#000000` | `#0030b8` | 2px rules, 4px top band |

"Match system" picks Paper or Slate from the OS setting. Contrast, measured with the WCAG
formula on `paper`: ink 13.5 to 21, ink-2 7.7 to 15, ink-3 5.5 to 10 (all body text clears 4.5:1),
accent as text 6.0 to 9.9, text on accent 6.0 to 9.9.

Charts use one accent hue for magnitude (bars, commute) and the validated categorical set
(blue, orange, green, yellow, magenta; light and dark steps) for reply types, always with a
legend and a number, never color alone. Status is a small square marker plus a word.

## 3. Typography

Three self-hosted, open-licensed families (no requests leave the machine; licenses are in
`static/fonts/`):

- **Fraunces** 500/600: headings, the wordmark and the large figures. A soft serif that is not a
  default.
- **IBM Plex Sans** 400/500/600: all interface text.
- **IBM Plex Mono** 400/500: dates, numbers in tables, scores, axis labels (tabular figures).

Scale (px): 11.5 labels (uppercase, +0.08em), 12.5 hints, 14 and 15 text, 19 to 24 section titles,
40 figures. Lines of explanatory text stop at about 62 characters.

## 4. Components

- **Figures row:** four to six numbers on a ruled strip, large serif numerals, uppercase caption.
- **Section:** a `rule-strong` hairline, serif title, one-line subtitle. Not a box.
- **Queue card:** the one place a bordered box is used (a repeated unit), radius 4, no shadow.
- **Table:** uppercase captions, hairline rows, mono right-aligned numbers.
- **Score:** a small outlined mono numeral with an accent wash.
- **Status:** an 8px square marker (solid sent, hollow queued, muted skipped, alert blocked).
- **Buttons:** radius 4, outlined; one filled accent button per context.
- **Inputs:** radius 3, `paper` fill, 1px rule, accent focus ring plus visible `:focus-visible`.
- **Theme menu:** keyboard operable (arrows, Escape), each entry with a two-color swatch.

## 5. Layout principles

One column of content, 1180px maximum, 20px gutters. Overview is the single asymmetric screen
(7/5 and 5/7 splits on a 12-column grid). Settings has a sticky section index on the left and
single-column sections on the right. Vertical rhythm: 34 to 48px between sections.

## 6. Depth and elevation

None: no shadows, blur or glows. Separation comes from rules, spacing and tint. The only layers
are the settings drawer (a 2px left rule), the theme menu (1px strong border) and the toast.

## 7. Do and don't

Do: tint neutrals; keep three type roles; use rules for structure; label axes and bars directly;
keep motion to a 180ms fade; respect `prefers-reduced-motion`; keep touch targets generous on
phones; test every theme at 390px and 1280px.

Don't (the usual tells of generated interfaces, taken from the
[Impeccable](https://github.com/pbakaus/impeccable) anti-pattern list): Inter, Arial or system
fonts as the identity; pure black or gray text; gray text on colored backgrounds; cards inside
cards or a card around everything; an icon tile above every heading; purple-to-blue gradients;
side-tab borders and dark glows; bounce or elastic easing; emoji as icons.

## 8. Responsive behavior

Below 900px the overview collapses to one column and the figures to two per row; below 960px the
settings index is hidden; the header wraps (chips, kill switch, theme menu). Tables scroll
horizontally instead of shrinking text.

## 9. Agent prompt guide

When extending the UI: read this file and `app.css` first, use the role tokens only (never raw
hex in markup or scripts), add a new theme by defining the whole token set and checking the ratios
above, keep Fraunces for display and figures only, and run the dashboard in all five themes
before committing. The Bavarian lozenge is a motif for the header band and empty states of the
two Bavarian themes only; do not spread it over content. The density, variance and motion dials
(a framing borrowed from [taste-skill](https://github.com/Leonxlnx/taste-skill)) are set here to
dense, low and minimal.
