"""Drive the real web page in headless Chromium with a fake microphone (a WAV file).

Runs inside the official Playwright image (no system libraries needed on the host):
  docker run --rm --network host -v "$PWD:/work" -w /work mcr.microsoft.com/playwright/python:v1.65.2-noble \
      python scripts/browser_check.py --url http://127.0.0.1:17860 --wav evals/audio/hi01.wav
Chrome's --use-file-for-fake-audio-capture plays the WAV as the microphone (it loops). The script
clicks Talk (live WebRTC), waits for the first answered turn, then tries Hold to talk (HTTP), and
saves screenshots + the page text to examples/browser/.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import wave

from playwright.sync_api import sync_playwright


def padded_wav(src: str, dst: str, lead_s=1.0, tail_s=4.0):
    with wave.open(src, "rb") as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    silence = lambda s: b"\x00" * int(s * params.framerate) * params.sampwidth * params.nchannels
    with wave.open(dst, "wb") as o:
        o.setparams(params)
        o.writeframes(silence(lead_s) + frames + silence(tail_s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:17860")
    ap.add_argument("--wav", default="evals/audio/en01.wav")
    ap.add_argument("--out", default="examples/browser")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    fake = os.path.abspath(os.path.join(a.out, "_fake_mic.wav"))
    padded_wav(a.wav, fake)
    result = {"wav": a.wav, "url": a.url}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                    f"--use-file-for-fake-audio-capture={fake}", "--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(permissions=["microphone"], viewport={"width": 900, "height": 900})
        page = ctx.new_page()
        console = []
        page.on("console", lambda m: console.append(m.text))
        page.goto(a.url)
        # 1) live WebRTC
        t0 = time.time()
        page.click("#talk")
        try:
            page.wait_for_selector("#log .turn", timeout=90_000)
            result["webrtc"] = {"ok": True, "seconds_to_first_turn": round(time.time() - t0, 1),
                                "turn_text": page.inner_text("#log .turn"), "status": page.inner_text("#status")}
        except Exception as e:
            result["webrtc"] = {"ok": False, "error": str(e)[:300], "status": page.inner_text("#status")}
        page.screenshot(path=os.path.join(a.out, "webrtc_turn.png"), full_page=True)
        page.click("#talk")  # stop
        time.sleep(1)
        # 2) push-to-talk (HTTP)
        n_before = page.locator("#log .turn").count()
        box = page.locator("#ptt").bounding_box()
        page.mouse.move(box["x"] + 5, box["y"] + 5)
        page.mouse.down()
        time.sleep(6.5)          # hold while the fake mic plays the question
        page.mouse.up()
        try:
            page.wait_for_function(f"document.querySelectorAll('#log .turn').length > {n_before}", timeout=90_000)
            result["push_to_talk"] = {"ok": True, "turn_text": page.locator("#log .turn").first.inner_text()}
        except Exception as e:
            result["push_to_talk"] = {"ok": False, "error": str(e)[:300], "status": page.inner_text("#status")}
        page.screenshot(path=os.path.join(a.out, "page_after_both.png"), full_page=True)
        result["console"] = console[-20:]
        b.close()
    os.remove(fake)
    with open(os.path.join(a.out, "browser_check.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
