"""Shared pytest fixtures / path setup so `import src...` works from repo root."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
