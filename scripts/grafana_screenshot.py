"""Screenshot the provisioned Grafana dashboard (runs in the Playwright image, like browser_check.py).

  docker run --rm --network host -v "$PWD:/work" -w /work mcr.microsoft.com/playwright/python:v1.65.2-noble \
      sh -c "pip install -q --break-system-packages playwright==1.65.2 && python3 scripts/grafana_screenshot.py"
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:13000"
out = sys.argv[2] if len(sys.argv) > 2 else "examples/grafana_dashboard.png"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1400, "height": 1150})
    page.goto(url + "/login")
    page.fill("input[name=user]", "admin")
    page.fill("input[name=password]", os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin"))
    page.click("button[type=submit]")
    time.sleep(3)
    page.goto(url + "/d/fleet-voice?orgId=1&from=now-30m&to=now&kiosk")
    time.sleep(10)
    page.screenshot(path=out, full_page=True)
    b.close()
print("wrote", out)
