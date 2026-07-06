# Wimbledon Player Ratings

Editorially curated 0–100 grass-court ratings for the players featured in the
**Build-a-Champion** game — spanning roughly two decades of Wimbledon (2006–2025).

Everything lives in a single file: **[`ratings.csv`](ratings.csv)** (115 players:
57 men, 58 women).

## What's in the CSV

| Column | Meaning |
|--------|---------|
| `name` | Player name (identification only) |
| `tour` | `atp` (men) or `wta` (women) |
| `country` | IOC country code |
| `archetype` | Short editorial style tagline |
| `serve`, `return`, `forehand`, `backhand`, `net`, `consistency`, `clutch`, `stamina` | Base ratings, 0–100 |
| `wimbledon_best` | Best Wimbledon singles result: Champion / Finalist / Semi-finalist / Quarter-finalist / Last 16 (blank if none) |

The game applies a small **Wimbledon pedigree bonus** on top of the base ratings
(Champion +6, Finalist +4, Semi-finalist +3, Quarter-finalist +2, Last 16 +1,
capped at 100), so proven Wimbledon performers rate a little higher in play.

## How the ratings were made

**All ratings are editorially curated.** They are an approximate, subjective
interpretation of each player's game for entertainment — not official statistics,
not a data feed, and not affiliated with or endorsed by any player, the AELTC,
Wimbledon, the ATP or the WTA. Player names are used for identification only.

`ratings.csv` is the single source of truth and mirrors the roster embedded in
`../build-a-champion-game_2.html`.
