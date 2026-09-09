"""Shared paths and loaders. Everything downstream reads the compact index,
never the raw JSONL (707 MB for dataset_a)."""
from pathlib import Path
import json, glob, os

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

def load_index(ds=None):
    import pandas as pd
    df = pd.read_parquet(BUILD / "events.parquet")
    return df[df.ds == ds].copy() if ds else df

def load_gt_manifest(sess):
    f = Path(sess) / "gt_manifest.json"
    return json.load(open(f, encoding="utf-8")) if f.exists() else None
