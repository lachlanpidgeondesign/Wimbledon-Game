"""Compute each roster player's best Wimbledon result from the raw match data.

Best result = deepest round reached across all Wimbledon draws in the dataset.
Emitted as a name -> code map (W/F/SF/QF/R16) for the game roster.
"""
import csv
import glob
import re
import unicodedata

RAW = "wimbledon-ratings/data/raw"
DEPTH = {"R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7}

best = {}  # name -> (depth, round_code, won_final)


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("-", " ")
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


files = glob.glob(f"{RAW}/atp_matches_*.csv") + glob.glob(f"{RAW}/wta_matches_*.csv")
for f in files:
    with open(f, newline="", encoding="latin-1") as fh:
        for row in csv.DictReader(fh):
            if row.get("tourney_name") != "Wimbledon":
                continue
            rnd = row.get("round", "")
            if rnd not in DEPTH:
                continue
            d = DEPTH[rnd]
            for name, is_winner in ((row["winner_name"], True), (row["loser_name"], False)):
                champ = rnd == "F" and is_winner
                cur = best.get(name)
                if cur is None or (d, champ) > (cur[0], cur[2]):
                    best[name] = (d, rnd, champ)


def code(rnd, champ):
    if rnd == "F":
        return "W" if champ else "F"
    if rnd in ("SF", "QF", "R16"):
        return rnd
    return None


results = {}
for name, (d, rnd, champ) in best.items():
    c = code(rnd, champ)
    if c:
        results[norm(name)] = (name, c)

html = open("build-a-champion-game_2.html", encoding="utf-8").read()
roster = re.findall(r'\{n:"([^"]+)"', html)

order = {"W": 0, "F": 1, "SF": 2, "QF": 3, "R16": 4}
out, missing = [], []
for rn in roster:
    key = norm(rn)
    if key in results:
        out.append((rn, results[key][1]))
    else:
        missing.append(rn)

out.sort(key=lambda x: (order[x[1]], x[0]))
print(f"roster players: {len(roster)}  achievers: {len(out)}  no-bonus: {len(missing)}")
print("\n== ACHIEVERS ==")
for nm, c in out:
    print(f"{c:4} {nm}")
print("\n== NO BONUS (never past R32) ==")
print(", ".join(missing))

js = ", ".join(f'"{nm}":"{c}"' for nm, c in sorted(out, key=lambda x: x[0]))
print("\n== JS MAP ==")
print("{" + js + "}")
