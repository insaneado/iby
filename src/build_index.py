"""Flatten raw events.jsonl -> one compact Parquet table (+ a side file for
extracted_text). Run once; every later stage reads the Parquet.

707 MB of dataset_a JSONL collapses to a few MB here, which is what makes
iterating on the segmenter cheap.
"""
import json, sys, time
import pandas as pd
from common import DATA, BUILD, sessions, chunk_files

def g(d, *path, default=None):
    """Safe nested get."""
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d

def flatten(e, ds):
    p = e.get("payload") or {}
    c = e.get("context") or {}
    t = e["event_type"]
    r = {
        "ds": ds,
        "session_id": e.get("session_id"),
        "chunk_id": g(e, "correlation", "chunk_id"),
        "seq": g(e, "correlation", "sequence_number"),
        "event_id": e.get("event_id"),
        "ts_ms": e.get("timestamp_ms"),
        "event_type": t,
        "layer": e.get("layer"),
        "gap_ms": g(e, "correlation", "ms_since_last_event"),
        "machine": g(e, "source", "machine_id"),
        "user": g(e, "source", "username_hash"),
        "app": g(c, "active_app", "app_name"),
        "proc": g(c, "active_app", "process_name"),
        "title": g(c, "active_app", "window_title"),
        "url": g(c, "active_browser_tab", "url"),
        "tab_title": g(c, "active_browser_tab", "title"),
        "has_text": bool(g(c, "extracted_text", "text")),
    }
    # --- per-event-type payload extraction ---
    if t == "keystroke":
        m = p.get("modifiers") or {}
        r.update(key=p.get("key"), char=p.get("character"),
                 mods="+".join(k for k, v in m.items() if v) or None,
                 el_name=g(p, "target_field", "name"),
                 el_type=g(p, "target_field", "control_type"),
                 el_value=g(p, "target_field", "value"))
    elif t == "shortcut":
        m = p.get("modifiers") or {}
        r.update(key="+".join(p.get("keys") or []),
                 mods="+".join(k for k, v in m.items() if v) or None,
                 hint=p.get("action_hint"))
    elif t in ("mouse_click", "mouse_double_click"):
        r.update(el_name=g(p, "target_element", "name"),
                 el_type=g(p, "target_element", "control_type"),
                 el_value=g(p, "target_element", "value"))
    elif t == "browser_click":
        a = g(p, "element", "attributes") or {}
        r.update(url=p.get("url") or r["url"],
                 el_id=a.get("id"), el_class=a.get("class"),
                 el_tag=g(p, "element", "tag"),
                 el_sel=g(p, "element", "css_selector"),
                 el_name=a.get("placeholder") or a.get("aria-label"))
    elif t == "browser_form_input":
        f = p.get("field") or {}
        r.update(url=p.get("url") or r["url"], el_id=f.get("id"),
                 el_name=f.get("label") or f.get("placeholder"),
                 el_type=f.get("input_type"), el_sel=f.get("css_selector"))
    elif t == "browser_navigation":
        r.update(url=p.get("url") or r["url"], prev_url=p.get("previous_url"),
                 el_name=p.get("page_title"), hint=p.get("navigation_type"))
    elif t == "app_switch":
        r.update(new_app=g(p, "new_app", "app_name"),
                 prev_app=g(p, "previous_app", "app_name"),
                 new_title=g(p, "new_app", "window_title"),
                 prev_title=g(p, "previous_app", "window_title"),
                 hint=p.get("trigger"))
    elif t == "window_title_change":
        r.update(new_title=p.get("new_title"), prev_title=p.get("previous_title"))
    elif t == "clipboard_change":
        r.update(clip_len=p.get("text_length"), hint=p.get("content_type"))
    elif t == "screenshot_smart":
        r.update(hint=p.get("trigger_reason"),
                 shot=g(p, "file_reference", "filename"))
    elif t == "text_input_complete":
        r.update(el_value=p.get("final_text"), el_name=g(p, "target_field", "name"))
    return r

def main():
    rows, texts = [], []
    for ds in ("dataset_a", "dataset_b"):
        t0 = time.time()
        n = 0
        for sess in sessions(ds):
            for f in chunk_files(sess):
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        e = json.loads(line)
                        rows.append(flatten(e, ds))
                        n += 1
                        txt = g(e, "context", "extracted_text", "text")
                        if txt:
                            texts.append({"event_id": e["event_id"],
                                          "session_id": e.get("session_id"),
                                          "ts_ms": e["timestamp_ms"], "text": txt})
        print(f"{ds}: {n} events, {time.time()-t0:.0f}s", flush=True)

    df = pd.DataFrame(rows)
    # stable chronological order within each session
    df = df.sort_values(["ds", "session_id", "ts_ms", "seq"]).reset_index(drop=True)
    for col in ("key", "char", "mods", "hint", "el_id", "el_class", "el_tag",
                "el_sel", "el_name", "el_type", "el_value", "new_app", "prev_app",
                "new_title", "prev_title", "prev_url", "shot"):
        if col not in df:
            df[col] = None
    df.to_parquet(BUILD / "events.parquet", index=False)
    pd.DataFrame(texts).to_parquet(BUILD / "extracted_text.parquet", index=False)
    print(f"\nevents.parquet  rows={len(df)}  cols={len(df.columns)}")
    print(f"extracted_text.parquet  rows={len(texts)}")
    print(df.groupby("ds").agg(sessions=("session_id", "nunique"), events=("ts_ms", "size")))

if __name__ == "__main__":
    sys.path.insert(0, str(BUILD.parent / "src"))
    main()
