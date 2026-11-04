"""Render docs/CREDIT_USAGE.md to docs/CREDIT_USAGE.pdf (A4, page numbers, generation note in the footer).

The PDF is the markdown, unchanged: no numbers are added or rounded. Needs the dev tools (`markdown`, `playwright`)
and an installed Chrome:

    .venv\\Scripts\\python docs\\make_credit_pdf.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

DOCS = Path(__file__).parent
SRC, OUT = DOCS / "CREDIT_USAGE.md", DOCS / "CREDIT_USAGE.pdf"

CSS = """
@page { size: A4; margin: 16mm 12mm 18mm 12mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 9.5pt; line-height: 1.4; color: #111; }
h1 { font-size: 17pt; margin: 0 0 8px; } h2 { font-size: 12.5pt; margin: 16px 0 6px; border-bottom: 1px solid #ccc; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; table-layout: auto; }
th, td { border: 1px solid #bbb; padding: 3px 5px; vertical-align: top; text-align: left; font-size: 8.3pt;
         overflow-wrap: break-word; }
th { background: #eef0f2; }
tr { page-break-inside: avoid; }
code { font-family: Consolas, monospace; font-size: 8pt; overflow-wrap: break-word; word-break: break-all; }
a { color: #0a58ca; text-decoration: none; }
"""


def main() -> None:
    body = markdown.markdown(SRC.read_text(encoding="utf-8"), extensions=["tables"])
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    footer = ("<div style='font-size:7.5pt;width:100%;padding:0 12mm;color:#555;display:flex;"
              "justify-content:space-between;font-family:Segoe UI,Arial,sans-serif'>"
              f"<span>Generated {date.today().isoformat()} from docs/CREDIT_USAGE.md</span>"
              "<span>Page <span class='pageNumber'></span> of <span class='totalPages'></span></span></div>")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(OUT), format="A4", print_background=True, display_header_footer=True,
                 header_template="<span></span>", footer_template=footer,
                 margin=dict(top="16mm", bottom="18mm", left="12mm", right="12mm"))
        browser.close()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
