"""Resolve device names to the widget's slug and OS version by clicking through
the 'Most popular products' tiles on the device chooser."""
import sys

from playwright.sync_api import sync_playwright

BASE = "https://www.cricketwireless.com/support/device-tutorials"
names = sys.argv[1:] or ["iPhone 13", "Moto G - 2025", "Moto G Stylus 5G (2024)", "Galaxy A15 5G"]

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    for name in names:
        pg.goto(BASE + "#/devices", wait_until="domcontentloaded")
        pg.wait_for_timeout(4000)
        try:
            pg.get_by_text(name, exact=True).first.click(timeout=5000)
            pg.wait_for_selector("a[href*='#/tutorial/']", timeout=30000)
            pg.wait_for_timeout(1500)
            n = pg.evaluate("document.querySelectorAll(\"a[href*='#/tutorial/']\").length")
            print(f"{name:28} -> {pg.url.split('#')[1]}  ({n} links visible)")
        except Exception as e:
            print(f"{name:28} -> FAILED {type(e).__name__}")
    b.close()
