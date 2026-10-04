import sys
from playwright.sync_api import sync_playwright

src = sys.argv[1]   # html file path
out = sys.argv[2]   # output png

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1080, "height": 2400}, device_scale_factor=2)
    pg.goto("file://" + src)
    pg.wait_for_timeout(500)
    pg.screenshot(path=out, full_page=True)
    b.close()
    print("saved", out)
