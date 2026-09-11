"""A reconstruction of the client portal, for running the automation against.

The real portal lives on 127.0.0.1:5132-5134 on the operators' machines and is
not available here. Everything below is rebuilt from evidence in dataset B:

  element ids      #<prefix>-note, #btn-<prefix>-ok, #<prefix>-table
                                                       payload.element.css_selector
  screens          12 (system, screen) pairs           context.extracted_text breadcrumbs
  table schemas    5 distinct column sets, read from the printed header
  row data         984 real worklist rows              context.extracted_text
  status values    per screen (未処理->登録済み, 処理待ち->承認, 照合中->完了, ...)
  note placeholder per screen archetype                browser_form_input.field.label
  ports            5132 / 5133 / 5134                  active_browser_tab.url
  confirm message  "<row id>: 登録確定しました"           context.extracted_text

Each system serves several screens, reached at /<prefix>. The five archetypes
share a shape - id, employee/vendor id, name, three screen-specific columns, a
status - but not a schema, which is why the engine is configured per screen
rather than hard-coded to one table.

What this proves: the automation drives the real DOM contract across every
screen archetype. What it does not prove: that the production portal behaves the
same. Session handling, server-side validation, pagination and latency are all
unobserved, and that gap is stated as a risk in the report.
"""
from __future__ import annotations
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
_FIXTURE_FILE = HERE / "fixture.json"
if not _FIXTURE_FILE.exists():
    raise SystemExit(f"{_FIXTURE_FILE} not found. It is rebuilt from dataset B rather "
                     "than committed: run `python tool/extract_fixture.py` first.")
FIXTURE = json.loads(_FIXTURE_FILE.read_text(encoding="utf-8"))

PORTS = {"hr": 5132, "fin": 5133, "ops": 5134}

# system -> {prefix: fixture key}; a system may serve several screens
SCREENS: dict[str, dict[str, str]] = {}
for key, st in FIXTURE.items():
    SCREENS.setdefault(st["system"], {})[st["prefix"]] = key

PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>{system_name} - {screen}</title><style>
body{{font-family:'Meiryo',system-ui,sans-serif;margin:0;background:#f4f6f8;color:#1b2733}}
header{{background:#1f3a5f;color:#fff;padding:10px 18px;display:flex;gap:16px;align-items:baseline}}
header b{{font-size:15px}} header span{{font-size:12px;opacity:.85}}
main{{padding:16px 20px;max-width:1150px}}
h1{{font-size:16px;margin:0 0 4px}} .crumb{{font-size:12px;color:#5a6b7d;margin-bottom:12px}}
nav a{{font-size:12px;margin-right:12px;color:#1f4e8c;text-decoration:none}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:12px}}
th,td{{border:1px solid #dfe5ec;padding:5px 8px;text-align:left}}
th{{background:#eef2f6;font-weight:600}}
tr.sel{{outline:2px solid #1f6feb}}
tr[data-done="1"]{{color:#7c8794;background:#fafbfc}}
.panel{{margin-top:14px;background:#fff;border:1px solid #dfe5ec;padding:12px}}
textarea{{width:100%;height:64px;font-family:inherit;font-size:12px;padding:6px;
box-sizing:border-box;border:1px solid #c9d3de}}
button{{margin-top:8px;padding:6px 18px;background:#1f6feb;color:#fff;border:0;
font-size:13px;cursor:pointer}}
#status{{margin-top:8px;font-size:12px;color:#1a7f37;min-height:16px}}
</style></head><body>
<header><b>{system_name}</b><span>{operator}</span></header>
<main>
<nav>{navlinks}</nav>
<div class="crumb">ダッシュボード / {screen}</div>
<h1>{screen}</h1>
<div class="crumb"><span id="counts">{total} 件 · {pending} 件{pending_value}</span></div>
<table id="{p}-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
<div class="panel">
  <textarea id="{p}-note" placeholder="{placeholder}"></textarea>
  <button id="btn-{p}-ok">確定</button>
  <div id="status"></div>
</div>
</main>
<script>
const P="{p}", DONE="{done_value}";
let selected=null;
document.querySelectorAll(`#${{P}}-table tbody tr`).forEach(tr=>{{
  tr.addEventListener('click',()=>{{
    document.querySelectorAll(`#${{P}}-table tbody tr`).forEach(x=>x.classList.remove('sel'));
    tr.classList.add('sel'); selected=tr.dataset.rowId;
  }});
}});
document.getElementById(`btn-${{P}}-ok`).addEventListener('click',async()=>{{
  const note=document.getElementById(`${{P}}-note`).value;
  if(!selected){{document.getElementById('status').textContent='行を選択してください';return;}}
  const r=await fetch(location.pathname+'/confirm',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{row_id:selected,note:note}})}});
  const d=await r.json();
  const tr=document.querySelector(`tr[data-row-id="${{selected}}"]`);
  tr.dataset.status=DONE; tr.dataset.done="1";
  tr.querySelector('td:last-child').textContent=DONE;
  document.getElementById('counts').textContent=`${{d.total}} 件 · ${{d.pending}} 件`;
  document.getElementById('status').textContent=`${{selected}}: 登録確定しました`;
  document.getElementById(`${{P}}-note`).value=''; selected=null; tr.classList.remove('sel');
}});
</script></body></html>"""


class Portal(BaseHTTPRequestHandler):
    key = "hr"

    def _screen(self, path):
        pref = path.strip("/").split("/")[0]
        fk = SCREENS.get(self.key, {}).get(pref)
        return (pref, FIXTURE[fk]) if fk else (None, None)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", ""):                      # default to the busiest screen
            pref = max(SCREENS[self.key],
                       key=lambda p: len(FIXTURE[SCREENS[self.key][p]]["rows"]))
            self.send_response(302)
            self.send_header("Location", f"/{pref}")
            self.end_headers()
            return
        pref, st = self._screen(path)
        if st is None:
            self.send_error(404)
            return
        cols = st["columns"]
        head = "".join(f"<th>{c}</th>" for c in cols)
        body = ""
        for r in st["rows"]:
            tds = "".join(f"<td>{r.get(c,'')}</td>" for c in cols)
            done = "1" if r[cols[-1]] == st["done_value"] else "0"
            body += (f'<tr data-row-id="{r["ID"]}" data-status="{r[cols[-1]]}" '
                     f'data-done="{done}">{tds}</tr>')
        pending = sum(1 for r in st["rows"] if r[cols[-1]] == st["pending_value"])
        navlinks = "".join(
            f'<a href="/{p}">{FIXTURE[k]["screen"]}</a>'
            for p, k in SCREENS[self.key].items())
        html = PAGE.format(system_name=st["system_name"], operator=st["operator"],
                           screen=st["screen"], p=pref, head=head, body=body,
                           total=len(st["rows"]), pending=pending,
                           pending_value=st["pending_value"],
                           done_value=st["done_value"],
                           placeholder=st["placeholder"], navlinks=navlinks)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.endswith("/confirm"):
            self.send_error(404)
            return
        pref, st = self._screen(path[:-len("/confirm")])
        if st is None:
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        cols = st["columns"]
        for r in st["rows"]:
            if r["ID"] == req.get("row_id"):
                r[cols[-1]] = st["done_value"]
                r["_note"] = req.get("note", "")
                break
        pending = sum(1 for r in st["rows"] if r[cols[-1]] == st["pending_value"])
        payload = json.dumps({"ok": True, "total": len(st["rows"]),
                              "pending": pending}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def serve(key: str) -> HTTPServer:
    cls = type(f"Portal_{key}", (Portal,), {"key": key})
    srv = HTTPServer(("127.0.0.1", PORTS[key]), cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def serve_all():
    return {k: serve(k) for k in PORTS}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")     # screen names are Japanese; see src/common.py
    serve_all()
    for k, port in PORTS.items():
        for pref, fk in SCREENS.get(k, {}).items():
            st = FIXTURE[fk]
            print(f"  http://127.0.0.1:{port}/{pref:3}  {st['system_name']:14} "
                  f"{st['screen'][:16]:18} {len(st['rows']):4d} rows")
    print("serving; Ctrl-C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        sys.exit(0)
