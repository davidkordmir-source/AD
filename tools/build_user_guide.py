"""Render the Persian end-user guide using Chromium's RTL layout.

Requires Python's playwright package, Chromium, and Noto Naskh Arabic,
Noto Sans Arabic, and DejaVu Sans fonts. Example:
    python tools/build_user_guide.py --chromium /usr/bin/chromium
Only builds documentation; it does not change or build the application.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from pathlib import Path
import shutil

from playwright.async_api import async_playwright


async def build(chromium: str) -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "docs/FastViewshed_User_Guide_FA_v3.6.2.html"
    output = root / "downloads/FastViewshed_User_Guide_FA_v3.6.2.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    # Render from memory so no browser access to file:// or network is needed.
    illustration = root / "downloads/FastViewshed_3.6_Map.png"
    illustration_url = "data:image/png;base64," + base64.b64encode(
        illustration.read_bytes()
    ).decode("ascii")
    html = source.read_text(encoding="utf-8").replace(
        "../downloads/FastViewshed_3.6_Map.png", illustration_url
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=chromium,
            args=["--no-sandbox"],
        )
        try:
            page = await browser.new_page()
            await page.emulate_media(media="print")
            await page.set_content(html, wait_until="networkidle")
            await page.evaluate("document.fonts.ready")
            images_loaded = await page.evaluate(
                "Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)"
            )
            if not images_loaded:
                raise RuntimeError("A guide illustration failed to load")
            await page.pdf(
                path=str(output),
                format="A4",
                prefer_css_page_size=True,
                print_background=True,
                display_header_footer=True,
                header_template="<span></span>",
                footer_template=(
                    '<div style="width:100%;margin:0 16mm;display:flex;'
                    'justify-content:space-between;font:9px Arial;color:#516a7c">'
                    '<span>Fast Viewshed 3.6.2 | User Guide (FA)</span>'
                    '<span><span class="pageNumber"></span> / '
                    '<span class="totalPages"></span></span></div>'
                ),
            )
        finally:
            await browser.close()
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default=shutil.which("chromium"))
    args = parser.parse_args()
    if not args.chromium:
        parser.error("Pass the Chromium executable path with --chromium")
    asyncio.run(build(args.chromium))
