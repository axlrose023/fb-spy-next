from __future__ import annotations

from html import escape


def offline_browser_index(
    *,
    final_url: str,
    title: str | None,
    has_screenshot: bool,
    has_mhtml: bool,
    has_dom: bool,
) -> str:
    safe_title = escape(title or "Landing page snapshot")
    safe_url = escape(final_url, quote=True)
    links: list[str] = []
    if has_mhtml:
        links.append('<a href="browser/page.mhtml">Open complete MHTML snapshot</a>')
    if has_dom:
        links.append('<a href="browser/dom.html">Open captured DOM</a>')
    if final_url:
        links.append(f'<a href="{safe_url}" rel="noreferrer">Open original URL</a>')
    preview = (
        '<img src="browser/screenshot_loaded.png" '
        'alt="Browser-rendered landing page snapshot">'
        if has_screenshot
        else "<p>No screenshot was available for this capture.</p>"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #f4f6f5; color: #18211d; font: 14px/1.5 Arial, sans-serif; }}
    header {{ padding: 18px 22px; background: #fff; border-bottom: 1px solid #dfe5e2; }}
    h1 {{ margin: 0 0 6px; font-size: 18px; }}
    p {{ margin: 0; color: #5d6963; overflow-wrap: anywhere; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; }}
    a {{ color: #087a55; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 20px; }}
    img {{ display: block; width: 100%; height: auto; background: #fff; border: 1px solid #dfe5e2; }}
  </style>
</head>
<body>
  <header>
    <h1>{safe_title}</h1>
    <p>{safe_url}</p>
    <nav>{"".join(links)}</nav>
  </header>
  <main>{preview}</main>
</body>
</html>
"""
