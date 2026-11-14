"""Equivara – lokale Ablage für Bestenliste und Einstellungen.

Dateien liegen standardmäßig in ~/.equivara (leaderboard.json, settings.json).
Geschrieben wird atomar (temporäre Datei + os.replace). Nur Standardbibliothek.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from pathlib import Path

__all__ = [
    "DEFAULT_DIR", "MAX_ENTRIES", "load_leaderboard", "add_entry", "entry_from_engine",
    "load_settings", "save_settings",
]

DEFAULT_DIR = Path.home() / ".equivara"
LEADERBOARD_FILE = "leaderboard.json"
SETTINGS_FILE = "settings.json"
MAX_ENTRIES = 100


def _leaderboard_path(path) -> Path:
    return Path(path) if path is not None else DEFAULT_DIR / LEADERBOARD_FILE


def _settings_path(path) -> Path:
    return Path(path) if path is not None else DEFAULT_DIR / SETTINGS_FILE


def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _score_of(entry) -> float:
    try:
        return float(entry.get("score", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _sorted(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=_score_of, reverse=True)


def load_leaderboard(path: Path | None = None) -> list[dict]:
    """Bestenliste absteigend nach Score; fehlende/kaputte Datei -> []."""
    data = _read_json(_leaderboard_path(path))
    if isinstance(data, dict):
        data = data.get("entries")
    if not isinstance(data, list):
        return []
    return _sorted([e for e in data if isinstance(e, dict)])


def add_entry(entry: dict, path: Path | None = None) -> list[dict]:
    """Eintrag hinzufügen, höchstens MAX_ENTRIES behalten, neue Liste zurückgeben."""
    p = _leaderboard_path(path)
    entry = dict(entry)
    entry.setdefault("date", _dt.datetime.now().isoformat(timespec="seconds"))
    entries = _sorted(load_leaderboard(p) + [entry])[:MAX_ENTRIES]
    _write_json_atomic(p, entries)
    return entries


def entry_from_engine(name: str, engine) -> dict:
    """Bestenlisten-Eintrag aus dem aktuellen Zustand einer EquivaraEngine."""
    last = engine.history[-1] if getattr(engine, "history", None) else {}
    sc = engine.score() if hasattr(engine, "score") else {"total": 0.0, "grade": "F"}
    return {
        "name": str(name).strip() or "Unbenannt",
        "scenario": getattr(engine, "scenario", "standard"),
        "events": bool(getattr(engine, "events_enabled", False)),
        "score": round(float(sc["total"]), 2),
        "grade": sc["grade"],
        "population": float(last.get("population", getattr(engine, "population", 0.0))),
        "environment": float(last.get("environment", getattr(engine, "environment", 0.0))),
        "debt": float(last.get("debt", getattr(engine, "debt", 0.0))),
        "food_pc": float(last.get("food_pc", getattr(engine, "food_pc", 0.0))),
        "date": _dt.datetime.now().isoformat(timespec="seconds"),
    }


def load_settings(path=None) -> dict:
    """Einstellungen laden; fehlend/kaputt -> {}."""
    data = _read_json(_settings_path(path))
    return data if isinstance(data, dict) else {}


def save_settings(settings: dict, path=None) -> None:
    _write_json_atomic(_settings_path(path), dict(settings))
