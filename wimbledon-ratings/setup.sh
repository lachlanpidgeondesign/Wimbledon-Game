#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# One-command setup + build for the Wimbledon ratings pipeline.
#
#   ./setup.sh                 # full: venv + install + tests + build everything
#   ./setup.sh --quick         # faster build: top-25 players per tour
#   ./setup.sh --skip-tests    # skip the test suite
#   ./setup.sh --offline       # build from already-downloaded data (no fetch)
#   ./setup.sh --limit 50      # build top-50 per tour
#
# Safe to re-run: it reuses the virtual environment if it already exists.
# -----------------------------------------------------------------------------
set -euo pipefail

# Always run from the directory this script lives in, wherever it's called from.
cd "$(dirname "${BASH_SOURCE[0]}")"

# ---- parse simple flags -----------------------------------------------------
RUN_TESTS=1
RUN_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick)       RUN_ARGS+=("--limit" "25"); shift ;;
    --limit)       RUN_ARGS+=("--limit" "$2"); shift 2 ;;
    --offline)     RUN_ARGS+=("--offline"); shift ;;
    --skip-tests)  RUN_TESTS=0; shift ;;
    -h|--help)     grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)             echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$1"; }

# ---- corporate proxy auto-discovery (WPAD/PAC) ------------------------------
# CLI tools (pip, requests) don't read the system PAC file the way browsers do,
# so on a locked-down corporate network they time out. If direct access fails,
# read the proxy host:port straight out of the PAC file and export it. Nothing
# is hardcoded — it works for whatever proxy your PAC returns.
ensure_proxy() {
  if [[ -n "${https_proxy:-}${HTTPS_PROXY:-}" ]]; then
    ok "Proxy already set ($https_proxy)"; return
  fi
  if curl -sS --max-time 8 -I https://pypi.org/simple/ >/dev/null 2>&1; then
    ok "Direct internet access"; return
  fi
  step "Direct access blocked — discovering corporate proxy (WPAD)"
  local pac proxy
  pac=$(scutil --proxy 2>/dev/null | awk -F' : ' '/ProxyAutoConfigURLString/{print $2}')
  [[ -z "$pac" ]] && pac="http://wpad/wpad.dat"
  proxy=$(curl -s --max-time 10 "$pac" 2>/dev/null \
            | grep -oE 'PROXY [A-Za-z0-9._-]+:[0-9]+' | tail -1 | awk '{print $2}')
  if [[ -n "$proxy" ]]; then
    export http_proxy="http://$proxy"  https_proxy="http://$proxy"
    export HTTP_PROXY="$http_proxy"    HTTPS_PROXY="$https_proxy"
    ok "Using proxy $proxy"
  else
    echo "Could not auto-discover a proxy. Set it manually, then re-run:" >&2
    echo "  export https_proxy=http://HOST:PORT http_proxy=http://HOST:PORT" >&2
    exit 1
  fi
}

# ---- 1. find Python ---------------------------------------------------------
step "Checking Python"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.9+ first (https://www.python.org/downloads/)." >&2
  exit 1
fi
python3 --version
ok "Python found"

# ---- 2. virtual environment -------------------------------------------------
step "Setting up virtual environment (.venv)"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  ok "Created .venv"
else
  ok "Reusing existing .venv"
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# ---- 3. dependencies --------------------------------------------------------
ensure_proxy
step "Installing dependencies"
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt
pip install pytest >/dev/null
ok "Dependencies installed"

# ---- 4. tests (offline, no network needed) ----------------------------------
if [[ "$RUN_TESTS" -eq 1 ]]; then
  step "Running test suite"
  pytest -q
  ok "Tests passed"
else
  step "Skipping tests (--skip-tests)"
fi

# ---- 5. build the ratings ---------------------------------------------------
step "Building ratings  (python run.py ${RUN_ARGS[*]:-})"
python run.py "${RUN_ARGS[@]}"

# ---- 6. done ----------------------------------------------------------------
step "Done"
cat <<'EOF'
Your results are in  data/processed/ :
  • players.json          the deliverable (every player, six ratings)
  • review.csv            open in Excel — ratings needing a human eye are at the top
  • licence_map.csv       what's safe to publish vs. needs licensing before launch
  • ratings_explain.json  the full "why" behind every number

Re-run anytime with:   ./setup.sh            (full)
                       ./setup.sh --quick    (fast 25-per-tour preview)
EOF
