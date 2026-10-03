"""Record demo clips from the running app (python3 -m navigator.web).

    PORT=8801 ~/.venvs/video/bin/python video/record.py [clip ...]     # video/clips/*.webm
"""
import os
import pathlib
import shutil
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
OUT = HERE / "clips"
URL = f"http://127.0.0.1:{os.environ.get('PORT', '8801')}/"


def glide(page, selector, steps=40, pause=18, offset=90):
    y0 = page.evaluate("window.scrollY")
    y1 = page.evaluate(f"document.querySelector({selector!r}).getBoundingClientRect().top + window.scrollY - {offset}")
    for i in range(1, steps + 1):
        page.evaluate(f"window.scrollTo(0, {y0 + (y1 - y0) * i / steps})")
        page.wait_for_timeout(pause)


def clip(browser, name, act, start="?id=A0001"):
    tmp = OUT / f"_{name}"
    shutil.rmtree(tmp, ignore_errors=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(tmp),
                              record_video_size={"width": 1280, "height": 720}, color_scheme="light")
    ctx.add_init_script("try{localStorage.clear()}catch(e){}")
    page = ctx.new_page()
    page.goto(URL + start, wait_until="networkidle")
    page.wait_for_timeout(900)
    act(page)
    video = page.video
    ctx.close()
    pathlib.Path(video.path()).replace(OUT / f"{name}.webm")
    shutil.rmtree(tmp, ignore_errors=True)
    print(name, flush=True)


def search(page, text, pick):
    page.click("#q")
    page.keyboard.type(text, delay=45)
    page.wait_for_timeout(500)
    page.click(f'#addrList button[data-id="{pick}"]')
    page.wait_for_timeout(1200)


def lookup(page):                     # LA: state cap superseded by the RSO, reasons, the quote
    page.wait_for_timeout(1500)
    glide(page, ".cat", steps=40)
    page.wait_for_timeout(3500)
    page.click(".cat .rule details.src summary")
    page.wait_for_timeout(800)
    glide(page, ".cat .rule details.src", steps=30, offset=260)
    page.wait_for_timeout(4000)


def unknown(page):                    # a building whose answer depends on a fact the record lacks
    search(page, "berkeley", os.environ.get("UNKNOWN_ID", "A0005"))
    page.wait_for_timeout(1500)
    glide(page, ".b-unknown", steps=40, offset=200)
    page.wait_for_timeout(4500)


def timetravel(page):                 # T1: California AB 325 before / after 2026-01-01
    page.evaluate("document.querySelector('#asof').value='2025-12-31'; document.querySelector('#asof').dispatchEvent(new Event('change'))")
    page.wait_for_timeout(1200)
    glide(page, ".cat:last-of-type", steps=30)
    page.wait_for_timeout(3500)
    page.evaluate("document.querySelector('#asof').value='2026-01-02'; document.querySelector('#asof').dispatchEvent(new Event('change'))")
    page.wait_for_timeout(1200)
    glide(page, ".cat:last-of-type", steps=10)
    page.wait_for_timeout(3000)


def jersey(page):                     # T3: FAIR Act not yet effective + conflict flag in Jersey City
    search(page, "jersey", os.environ.get("JC_ID", "A0008"))
    glide(page, ".conflict", steps=40, offset=260)
    page.wait_for_timeout(5000)


def spanish(page):
    page.click('[data-lang="es"]')
    page.wait_for_timeout(1500)
    glide(page, ".cat", steps=40)
    page.wait_for_timeout(4500)


def changes(page):
    page.click('[data-tab="changes"]')
    page.wait_for_timeout(1500)
    for t in ("T2", "T3", "T4", "T5"):
        glide(page, f"#bars-{t}", steps=25, offset=260)
        page.wait_for_timeout(1700)
    page.wait_for_timeout(1500)


def rules(page):
    page.click('[data-tab="rules"]')
    page.wait_for_timeout(2500)
    page.click(".rchip")
    page.wait_for_timeout(5000)


def pipeline(page):
    page.click('[data-tab="pipeline"]')
    page.wait_for_timeout(3500)
    glide(page, "#tab-pipeline h2", steps=40)
    page.wait_for_timeout(4000)


CLIPS = {"lookup": lookup, "unknown": unknown, "timetravel": timetravel, "jersey": jersey, "spanish": spanish,
         "changes": changes, "rules": rules, "pipeline": pipeline}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    want = sys.argv[1:] or list(CLIPS)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name in want:
            clip(b, name, CLIPS[name])
        b.close()
