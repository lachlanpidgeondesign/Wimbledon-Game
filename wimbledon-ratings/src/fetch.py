"""Phase A (Extract): download free open datasets and cache them locally.

We FETCH flat data files from the Jeff Sackmann GitHub repos rather than scraping
any official tournament site. That is more robust and avoids site terms-of-use
and database-right complications. Files are cached under data/raw/ so repeat runs
are offline and fast.

LICENCE: the Sackmann files are CC BY-NC-SA 4.0 (non-commercial). Fine for this
free prototype; the serve/return/net detail derived from them is flagged
prototype-only in the generated licence_map.csv.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import requests

from .utils import get_logger, project_root, tour_source

log = get_logger("fetch")


def ensure_proxy(timeout: int = 8) -> None:
    """Best-effort corporate proxy auto-discovery for locked-down networks.

    `requests` honours the http(s)_proxy env vars but, unlike a browser, does not
    read the system WPAD/PAC file. So if no proxy is set and a direct connection
    fails, we read the proxy host:port out of the PAC file and set the env vars.
    Quiet no-op when direct access already works or nothing can be discovered.
    """
    if os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY"):
        return
    try:
        requests.head("https://raw.githubusercontent.com", timeout=timeout)
        return  # direct access already works
    except requests.RequestException:
        pass

    pac_urls = []
    try:  # macOS: ask the system for its configured PAC URL
        out = subprocess.run(["scutil", "--proxy"], capture_output=True,
                             text=True, timeout=5).stdout
        m = re.search(r"ProxyAutoConfigURLString\s*:\s*(\S+)", out)
        if m:
            pac_urls.append(m.group(1))
    except Exception:
        pass
    pac_urls.append("http://wpad/wpad.dat")  # conventional WPAD fallback

    for pac in pac_urls:
        try:
            text = requests.get(pac, timeout=timeout).text
        except requests.RequestException:
            continue
        found = re.findall(r"PROXY\s+([A-Za-z0-9._-]+:\d+)", text)
        if found:
            proxy = "http://" + found[-1]
            os.environ["http_proxy"] = os.environ["https_proxy"] = proxy
            os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = proxy
            log.info("using auto-discovered proxy %s", found[-1])
            return
    log.warning("no direct internet and no proxy discovered - downloads may fail")

# Decade ranking files in the Sackmann repos (plus the live "current" file).
_RANKING_DECADES = ["00s", "10s", "20s", "current"]

# Match Charting Project files used for net + forehand/backhand signals.
_MCP_FILES = [
    "charting-{g}-matches.csv",
    "charting-{g}-stats-Overview.csv",
    "charting-{g}-stats-NetPoints.csv",
]


def _download(url: str, dest: Path, force: bool, timeout: int = 60) -> Path | None:
    """Download url -> dest with simple caching. Returns path or None on failure."""
    if dest.exists() and not force:
        log.debug("cached  %s", dest.name)
        return dest
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("FAILED  %s (%s)", url, exc)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    log.info("fetched %s (%d KB)", dest.name, len(resp.content) // 1024)
    return dest


def _tour_targets(cfg: dict, tour: str) -> list[tuple[str, str]]:
    """Build (url, filename) pairs for one tour's players, rankings and matches."""
    ts = tour_source(cfg, tour)
    base, y0, y1 = ts["base"], ts["year_start"], ts["year_end"]

    targets = [(f"{base}/{tour}_players.csv", f"{tour}_players.csv")]
    for decade in _RANKING_DECADES:
        fname = f"{tour}_rankings_{decade}.csv"
        targets.append((f"{base}/{fname}", fname))
    for year in range(y0, y1 + 1):
        fname = f"{tour}_matches_{year}.csv"
        targets.append((f"{base}/{fname}", fname))
    return targets


def _mcp_targets(cfg: dict) -> list[tuple[str, str]]:
    base = cfg["sources"]["sackmann"]["mcp_base"]
    targets = []
    for gender in ("m", "w"):
        for tmpl in _MCP_FILES:
            fname = tmpl.format(g=gender)
            targets.append((f"{base}/{fname}", fname))
    return targets


def fetch_all(cfg: dict, force: bool = False) -> Path:
    """Download every required file. Returns the cache directory.

    Missing files (e.g. a not-yet-published season, or MCP charting files) are
    logged and skipped; the rest of the pipeline degrades gracefully.
    """
    ensure_proxy()
    cache = project_root() / cfg["sources"]["cache_dir"]
    cache.mkdir(parents=True, exist_ok=True)

    targets: list[tuple[str, str]] = []
    for tour in ("atp", "wta"):
        targets += _tour_targets(cfg, tour)
    targets += _mcp_targets(cfg)

    ok = 0
    for url, fname in targets:
        if _download(url, cache / fname, force) is not None:
            ok += 1
    log.info("fetch complete: %d/%d files available in %s", ok, len(targets), cache)
    return cache
