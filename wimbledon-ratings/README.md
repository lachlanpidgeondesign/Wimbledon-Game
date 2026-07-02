# Wimbledon Player Ratings Pipeline

A one-off Python ETL that turns **free, open tennis data** into editorial
**0–100 grass-court ratings** — serve, return, forehand, backhand, net/volley,
consistency, plus **clutch** and **stamina** — for the **top ~50 most-notable men and
~50 women of 2006–2025** (configurable), on a **career / peak-grass** basis. Each player also gets
a short **archetype** tagline and an IOC **country** code. Output is a single
`players.json` (and a game-ready `game_roster.json`), plus full explainability and
an editorial-review worksheet.

> **Status: free MVP / prototype.** It is built on the best free data available,
> which includes **non-commercial** sources. Before any commercial launch, read
> [Licensing](#licensing) and the generated `data/processed/licence_map.csv`.

---

## Licensing

This is the single most important thing to understand.

| Data | Used for | Licence | Commercial? |
|------|----------|---------|-------------|
| Match results, scores, draws, rankings (facts) | in-house Elo, win%, ranking percentile, **consistency** | not copyrightable | ✅ usable now |
| Match **scorelines** (tiebreaks, deciding sets, 5-setters, minutes, rounds) | **clutch**, **stamina** | not copyrightable | ✅ usable now |
| Player **IOC country** + derived **archetype** tagline | **country**, **archetype** | facts / derived | ✅ usable now |
| Wikidata bio (optional) | handedness / country / height | CC0 | ✅ usable now |
| Sackmann ATP/WTA serve & return columns (via community mirrors) | **serve**, **return** | CC BY-NC-SA 4.0 | ❌ **non-commercial** |
| Sackmann **Match Charting Project** (net points, FH/BH winners/errors) | **net/volley**, FH/BH nudges | CC BY-NC-SA 4.0 | ❌ **non-commercial** |

> **Source note:** Jeff Sackmann removed the canonical `tennis_atp` / `tennis_wta`
> repos from his account, so the pipeline fetches the best surviving free mirrors
> (`stakah/tennis_atp`, `ppaulojr/tennis_wta`). The Match Charting Project is still
> on his account. Mirror URLs and per-tour year windows live in `config/sources.yaml`.

**Facts are free.** The *derived serve/return/net detail* is the part that is
non-commercial. The pipeline therefore tags every output field `clean` vs
`prototype` in `licence_map.csv`, so you know exactly what must be **licensed
(direct from Sackmann) or replaced (official / Opta / Stats Perform)** before
going commercial. `consistency`, `clutch`, `stamina`, `country` and `archetype`
are all derived from **facts** (results, scorelines, rounds) and are already fully
clean — only serve / return / net-volley / FH-BH nudges are prototype.

We **fetch open data files**; we do **not** scrape official tournament sites
(avoids site terms-of-use and EU/UK database-right issues, and is far more robust).

---

## Quick start

```bash
cd wimbledon-ratings
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python run.py                # download (cached) + build everything
python run.py --offline      # rebuild from cached raw data only
python run.py --limit 25     # debug: top-25 per tour, fast
pytest -q                    # run the test suite (no network needed)
```

Outputs are written to `data/processed/`.

---

## Data model

`players.json` records extend the brief's schema with the four clean dimensions:

```json
{
  "player_id": "roger-federer",
  "name": "Roger Federer",
  "tour": "atp",
  "country": "SUI",
  "ranking": 1,
  "serve": 94,
  "return": 78,
  "forehand": 93,
  "backhand": 80,
  "net_volley": 90,
  "consistency": 95,
  "clutch": 95,
  "stamina": 90,
  "archetype": "Forehand + Backhand"
}
```

`ranking` is the player's **career-best** (peak) singles ranking. `archetype` is a
short tagline derived from the player's two strongest shot ratings.

### Game roster (`game_roster.json`)

A parallel export in the **Build-a-Champion** game's compact schema — the same 300
players, ready to inline into the standalone HTML game:

```json
{ "n": "Roger Federer", "a": "Forehand + Backhand", "country": "SUI", "tour": "atp",
  "serve": 92, "ret": 94, "fh": 98, "bh": 98, "net": 86, "con": 97, "clutch": 95, "stam": 90 }
```

---

## Rating methodology

Every attribute is a weighted blend of **percentile-ranked** sub-metrics
(ranked **within tour**) mapped onto a **40–98** envelope. Tune all weights in
`config/weights.yaml` — no code changes needed.

| Attribute | Formula (weights in config) | Tier | Licence |
|-----------|------------------------------|------|---------|
| **Serve** | 0.35·ace% + 0.30·1st-serve-won% + 0.25·hold% + 0.10·2nd-serve-won% | data | prototype |
| **Return** | 0.50·return-pts-won% + 0.35·break% + 0.15·1st-return-won% | data | prototype |
| **Consistency** | 0.40·rank-pctile + 0.35·grass-Elo-pctile + 0.25·grass-win% | data | **clean** |
| **Clutch** | 0.50·tiebreak-win% + 0.50·deciding-set-win% *(shrunk)* | data / model | **clean** |
| **Stamina** | 0.50·long-match-win% + 0.30·deep-run + 0.20·avg-minutes | data / model | **clean** |
| **Net/Volley** | 0.65·net-win% + 0.35·net-volume *(charted)*, else compressed model | data / model | prototype |
| **Forehand** | quality index (peak Elo + peak rank) ± aggression ± charting-FH | model | prototype |
| **Backhand** | quality index ± return-strength ± 1H/2H prior ± charting-BH | model | prototype |

**Why forehand/backhand are modelled:** no *free* dataset carries a per-wing
quality metric at scale. They are derived from a transparent quality index plus
small, signed, documented nudges — and are **always flagged for editorial
review**. Licensing a shot-level feed (Opta/Hawk-Eye) later is the upgrade path.

**Why clutch/stamina are shrunk:** they are read straight from **scorelines**
(tiebreaks won, deciding sets won, 5-setters won, minutes played, rounds reached)
for grass matches. Because a rate over few matches is noisy — a journeyman going
3-for-3 in tiebreaks should not outrank Djokovic — each rate is regressed toward
the pooled tour mean via **empirical-Bayes shrinkage** `(won + k·prior)/(played + k)`.
Players with fewer than `MIN_CLUTCH_MATCHES` grass matches fall back to the quality
index. All inputs are facts, so both dimensions are **licence-clean**.

### Normalisation (`src/normalize.py`)

The reusable `scale_to_rating()`:

- **percentile based** — robust to scale and outliers;
- **winsorised** tails (default 2 / 98) so one freak value can't dominate;
- maps via `rank / (n+1)` so results sit **strictly inside** the band — never an
  extreme 0/100, and never even exactly 40/98;
- **per-tour** percentiles share one 40–98 envelope, so a WTA "95 serve" means
  elite-for-tour rather than being unfairly compared to ATP ace rates;
- NaN- and tie-safe; missing sub-metrics renormalise the remaining weights.

---

## Project structure

```
wimbledon-ratings/
├── config/
│   ├── sources.yaml            # dataset URLs, 2006–2025 window, licence flags
│   ├── weights.yaml            # formula weights + 40–98 envelope
│   ├── selection.yaml          # notability criteria, N per tour
│   ├── editorial_overrides.csv # manual rating overrides (audited)
│   └── backhand_type.csv       # curated one-/two-handed prior
├── src/
│   ├── fetch.py        # A: download free datasets (cached)
│   ├── ingest.py       # A: load + validate CSVs
│   ├── players.py      # B: Wimbledon filter + notability + top-N selection
│   ├── grass.py        # C: career-grass serve/return aggregates
│   ├── elo.py          # C: in-house overall + grass Elo (peak)
│   ├── net.py          # C: Match Charting net + FH/BH signals (best-effort)
│   ├── form.py         # C: scoreline parse → clutch/stamina facts (shrunk)
│   ├── normalize.py    # D: the reusable percentile → 40–98 normaliser
│   ├── ratings.py      # D: the six rating formulas
│   ├── explain.py      # D: per-(player,attribute) provenance
│   ├── editorial.py    # D: auto-flagging + override application
│   └── export.py       # D: players.json, explain, review, licence_map
├── tests/              # normaliser, ratings, selection (offline)
├── run.py              # orchestrator
└── requirements.txt
```

---

## Outputs (`data/processed/`)

| File | What it is |
|------|------------|
| `players.json` | the deliverable — every player in the extended schema (8 ratings + country + archetype) |
| `game_roster.json` | the same players in the Build-a-Champion game's compact schema, ready to inline |
| `ratings_explain.json` | full provenance: formula, source fields, raw values, percentiles, tier, licence, sample size, final rating |
| `review.csv` | flat, flag-sorted worksheet for the editorial pass |
| `licence_map.csv` | per-attribute clean-vs-prototype map + the pre-launch action |

---

## Editorial review workflow

A deliberate **two-pass** process:

1. **Data draft** — `run.py` computes everything and **auto-flags** any rating
   that is modelled (all FH/BH; net without charting), based on a thin grass
   sample, or a top/bottom-5% outlier.
2. **Editorial** — open `review.csv` (already sorted with flagged rows first),
   eyeball them, and record changes in `config/editorial_overrides.csv`:

   ```csv
   player_id,attribute,value,reviewer,note
   roger-federer,net_volley,95,ed,"Best grass volleyer of the era"
   ```

3. **Re-run** — overrides are applied and recorded in the explain output, so
   every manual change stays auditable. Lock and ship.

---

## Limitations & pre-launch checklist

- [ ] **Data window actually achieved** — the canonical Jeff Sackmann `tennis_atp` /
      `tennis_wta` repos were removed from his account, so the pipeline fetches the
      best surviving free community mirrors. These are frozen: **ATP 2006–2018**
      (`stakah/tennis_atp`) and **WTA 2006–2015** (`ppaulojr/tennis_wta`). That covers
      the Federer/Nadal/Djokovic/Murray and Williams/Sharapova/Azarenka era well but
      **excludes players who emerged later** (Alcaraz, Sinner, Swiatek, Gauff, …). To
      reach the present, point each tour's `base`/`year_end` in `config/sources.yaml`
      at a current mirror or a licensed feed.
- [ ] **WTA serve/return are modelled** — the free WTA mirror's match files carry no
      serve-stat columns, so women's serve & return fall back to the quality index
      (and are flagged for review). Men's serve/return are genuinely data-driven.
- [ ] **Clutch/stamina on thin samples** — players with few grass matches get a
      quality-index fallback; everyone else is shrunk toward the tour mean. Both are
      licence-clean (facts), but older mirror data is sparser, so treat them as
      editorial estimates and eyeball the flagged rows.
- [ ] **Licensing** — replace/clear every `prototype` field in `licence_map.csv`
      (serve, return, net/volley, FH/BH nudges) before commercial use.
- [ ] **Forehand/backhand** are modelled estimates (Elo/rank base + charting nudges)
      — budget editorial time, or license a shot-level feed.
- [ ] **Cross-era Elo** drifts over the period; ratings are percentile-within-period.
      Treat peak-Federer vs peak-Nadal as "great-for-their-era", not absolute.
- [ ] **Names** are factual; if you add photos/likenesses, clear image rights
      separately (out of scope here).

> Not legal advice — confirm data licensing with your legal team before launch.
