"""Render the Markdown reports to PDF via Chromium.

Chromium is used rather than a Python PDF library because the reports contain
Japanese, and headless Chromium already has the font fallback to typeset it
correctly. Playwright is a dependency of the Step 3 tool, so this adds none.
"""
from __future__ import annotations
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent

CSS = """
@page { size: A4; margin: 16mm 15mm; }
body { font-family: "Yu Gothic UI", "Meiryo", -apple-system, "Segoe UI", sans-serif;
       font-size: 10pt; line-height: 1.55; color: #14202b; max-width: 100%; }
h1 { font-size: 19pt; margin: 0 0 2mm; border-bottom: 2px solid #1f3a5f;
     padding-bottom: 2mm; }
h2 { font-size: 13pt; margin: 8mm 0 2mm; color: #1f3a5f;
     border-bottom: 1px solid #d5dde5; padding-bottom: 1mm; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 5mm 0 1.5mm; color: #2c4a6e; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0; font-size: 8.5pt;
        page-break-inside: avoid; }
th, td { border: 1px solid #ccd6e0; padding: 1.6mm 2.2mm; text-align: left;
         vertical-align: top; }
th { background: #eef2f6; font-weight: 600; }
code { background: #f2f5f8; padding: 0.4mm 1mm; border-radius: 2px;
       font-family: Consolas, monospace; font-size: 8.5pt; }
pre { background: #f6f8fa; padding: 3mm; border-left: 3px solid #1f3a5f;
      overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; font-size: 8pt; }
blockquote { border-left: 3px solid #9fb3c8; margin: 3mm 0; padding: 1mm 0 1mm 4mm;
             color: #3d5266; }
strong { color: #0b1620; }
hr { border: 0; border-top: 1px solid #d5dde5; margin: 6mm 0; }
a { color: #1f4e8c; text-decoration: none; }
"""


def build(src: Path, dest: Path):
    html = markdown.markdown(src.read_text(encoding="utf-8"),
                             extensions=["tables", "fenced_code", "sane_lists"])
    doc = (f'<!doctype html><html><head><meta charset="utf-8">'
           f"<style>{CSS}</style></head><body>{html}</body></html>")
    tmp = dest.with_suffix(".tmp.html")
    tmp.write_text(doc, encoding="utf-8")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page()
        p.goto(tmp.resolve().as_uri(), wait_until="networkidle")
        p.pdf(path=str(dest), format="A4", print_background=True,
              margin={"top": "16mm", "bottom": "16mm",
                      "left": "15mm", "right": "15mm"})
        b.close()
    tmp.unlink()
    print(f"  {dest.name}  {dest.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    for name in ("REPORT", "SUMMARY_JA", "step2_analysis"):
        src = HERE / f"{name}.md"
        if src.exists():
            build(src, HERE / f"{name}.pdf")
