"""Shared paths and loaders. Everything downstream reads the compact index,
never the raw JSONL (707 MB for dataset_a)."""
from pathlib import Path
from functools import lru_cache
import json, glob, os, sys


def _utf8_output():
    """Print Japanese without crashing on Windows.

    Most scripts here print Japanese - screen names, regulation text, labels. A
    Windows console accepts it, but once output is piped or redirected Python
    encodes with the ANSI code page (cp1252 on the machine this was built on),
    and the first Japanese character ends the run: `python tool/regulations.py
    > rules.txt` died on its fourth line with UnicodeEncodeError. Every entry
    point imports this module, so UTF-8 is set here, once.
    """
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if hasattr(stream, "reconfigure") and enc != "utf8":
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


_utf8_output()

ROOT = Path(__file__).resolve().parent.parent

# Data lives outside the repo (3.8 GB, gitignored). Defaults to ./data; a
# `config.local.json` with {"data_root": "..."} overrides it, so the datasets
# can sit wherever they were unpacked without copying them around.
_CFG = ROOT / "config.local.json"
DATA = (Path(json.load(open(_CFG, encoding="utf-8"))["data_root"])
        if _CFG.exists() else ROOT / "data")
BUILD = ROOT / "build"
OUT = ROOT / "out"
BUILD.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)

def sessions(ds):
    """ds in {'dataset_a','dataset_b'} -> sorted list of session dirs."""
    return sorted(p for p in (DATA / ds).glob("ses_*") if p.is_dir())

def chunk_files(sess):
    return sorted(Path(sess).glob("chunk_*/events.jsonl"))

def iter_events(sess):
    """Yield events of one session in timestamp order, across all chunks."""
    evs = []
    for f in chunk_files(sess):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    evs.append(json.loads(line))
    evs.sort(key=lambda e: (e["timestamp_ms"], e.get("correlation", {}).get("sequence_number") or 0))
    return evs

@lru_cache(maxsize=4)
def _read_index():
    import pandas as pd
    return pd.read_parquet(BUILD / "events.parquet")


def load_index(ds=None):
    """Cached: parameter sweeps call this hundreds of times and the Parquet
    read dominated the runtime. Returns a copy so callers cannot mutate it."""
    df = _read_index()
    return df[df.ds == ds].copy() if ds else df.copy()

def load_gt_manifest(sess):
    f = Path(sess) / "gt_manifest.json"
    return json.load(open(f, encoding="utf-8")) if f.exists() else None
