"""Splice the generated game_roster.json into the standalone game's inline ROSTER.

Reads data/processed/game_roster.json and rewrites the `const ROSTER=[ ... ];`
block in build-a-champion-game_2.html using the game's compact inline keys
(c=country, t=tour). Everything else in the HTML is left untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROSTER_JSON = HERE.parent / "data" / "processed" / "game_roster.json"
GAME_HTML = HERE.parent.parent / "build-a-champion-game_2.html"

ORDER = ["serve", "ret", "fh", "bh", "net", "con", "clutch", "stam"]


def js_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fmt_player(p: dict) -> str:
    parts = [
        f'n:{js_str(p["n"])}',
        f'a:{js_str(p.get("a", ""))}',
        f'c:{js_str(p.get("country", ""))}',
        f't:{js_str(p.get("tour", ""))}',
    ]
    parts += [f'{k}:{int(round(p[k]))}' for k in ORDER]
    return "  {" + ",".join(parts) + "}"


def main() -> None:
    players = json.loads(ROSTER_JSON.read_text())
    body = ",\n".join(fmt_player(p) for p in players)
    new_block = "const ROSTER=[\n" + body + "\n];"

    html = GAME_HTML.read_text()
    start = html.index("const ROSTER=[")
    end = html.index("];", start) + len("];")
    updated = html[:start] + new_block + html[end:]

    GAME_HTML.write_text(updated)
    print(f"ROSTER spliced: {len(players)} players "
          f"({sum(1 for p in players if p.get('tour') == 'atp')} atp / "
          f"{sum(1 for p in players if p.get('tour') == 'wta')} wta)")


if __name__ == "__main__":
    main()
