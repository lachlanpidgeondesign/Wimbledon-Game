# Design system — Wimbledon (dark)

A dark-mode games UI. Neutral black surfaces; the only two colours that carry
chroma are a grass **green** (primary action) and a royal **purple** (accent).
Heritage feel from a serif display face over a neutral sans body.

All colour, type, spacing and radius values live in `tokens.css`. **Read that
file and use its CSS custom properties. Never write raw hex, px sizes, or font
names inline.**

## Colour rules
- Use `var(--color-primary)` (green) for the main action on a view — CTAs,
  active/selected state. **One primary action per view.**
- Use `var(--color-accent)` (purple) for links, tags, highlights, and secondary
  emphasis — not for primary actions.
- Surfaces stay neutral: `--canvas`, `--surface`, `--surface-raised`. **Never
  tint a surface green or purple.**
- Purple is for headings, links, pills, borders and UI only — **never body
  text** (fails contrast at small sizes).
- Text on a coloured fill uses the paired `-on` token, never plain black/white:
  green fill → `--green-on`; purple-deep fill → `--purple-on`.
- Match results are the **only** place red may appear: use `var(--win)` (green)
  and `var(--loss)` (red) for set/round win–loss chips only — never on surfaces,
  body text, or actions.

## Typography rules
- Body, labels, buttons, and all UI text → `var(--font-body)` (Inter).
- Headings, pull-quotes, and editorial accents → `var(--font-display)` (Lora).
  **Never set Lora on paragraph/body copy.**
- Two weights only: 400 and 500.

## Examples

```css
/* ✅ correct */
.btn-primary {
  background: var(--color-primary);
  color: var(--green-on);
  border-radius: var(--radius-sm);
  font-family: var(--font-body);
}
.tag {
  background: var(--purple-deep);
  color: var(--purple-on);
  border-radius: var(--radius-pill);
}
.card-title { font-family: var(--font-display); }

/* ❌ wrong — raw hex, tinted surface, purple body text, Lora on body */
.card { background: #14211a; }              /* tint the surface: no */
.body { color: #B392E6; font-family: Lora; } /* purple + serif body: no */
.btn { background: #46C078; color: #000; }   /* raw hex + black on green: no */
```

## To flip which colour leads
If purple should be the identity colour instead of green, change only the two
aliases in `tokens.css`:
`--color-primary: var(--purple)` and `--color-accent: var(--green)`.
Do not rewrite components — they reference the aliases, not the raw colours.
