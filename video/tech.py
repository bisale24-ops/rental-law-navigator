"""Technical walkthrough, under 60 seconds. Synthesized narration."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from vdata import *  # noqa: F401,F403,E402
from look import STYLE  # noqa: E402,F401

VOICE = "en-US-AndrewNeural"
SCENES = [
    ("card:flow", "Module A: a model reads every document into a strict schema, twice, plus a third pass for "
                  "coverage limits. Code then checks every quote against the source."),
    ("clip:pipeline", f"Of {words(PROPOSED)} proposed rules, {words(DROPPED)} were dropped because their quote is not in "
                    f"the source. Nothing reaches the database without a real quote."),
    ("card:b", "Module B is plain code. The Census Geocoder finds the legal city; a house number check caught "
               "a Cambridge address placed in Boston. A missing year, or the cutoff year itself, is unknown, never a guess."),
    ("card:c", "Module C reruns the engine at each date. A new ordinance is one command: it is extracted, "
               "checked, and every address is compared with and without it."),
    ("card:end", "Every model answer is cached, so a rerun is exact and free. The narration is synthesized."),
]
CLIPS = {"pipeline": ("clips/pipeline.webm", 0)}
CARDS = {
    "flow": """<h1>Pipeline</h1><div class=flow>
      <div><b>Read</b>""" + f"{DOCS}" + """ documents: corpus plus official copies where robots.txt allows</div>
      <div><b>Extract</b>two reading passes + coverage pass, strict JSON schema</div>
      <div><b>Verify</b>every quote located in the source by code</div>
      <div><b>Answer</b>engine in plain code: 500 addresses × any date</div></div>""",
    "quotes": f"""<h1>The quote check</h1><table>
      <tr><td>Rules proposed by the model</td><td class=big>{PROPOSED}</td></tr>
      <tr><td>Quote found verbatim</td><td class="big ok">{EXACT}</td></tr>
      <tr><td>Repaired to the source's exact words</td><td class=big>{REPAIRED}</td></tr>
      <tr><td>Dropped: quote not in the source</td><td class="big warn">{DROPPED}</td></tr>
      <tr><td>Rules after merging duplicates</td><td class=big>{NRULES}</td></tr></table>""",
    "b": """<h1>Jurisdiction and coverage</h1><table>
      <tr><td>322-322.5 Western Ave, Cambridge</td><td class=warn>geocoder said Boston → house number mismatch → re-resolved: Cambridge</td></tr>
      <tr><td>Built 1979, cutoff June 13, 1979</td><td class=d>unknown: year built ≠ certificate date</td></tr>
      <tr><td>“3S-F-D-6U-NH”, no unit count</td><td class=ok>6 units, from the building description</td></tr>
      <tr><td>State cap + city rent control</td><td class=d>state rule superseded</td></tr></table>""",
    "c": """<h1>Change tracking</h1><pre>$ python3 -m navigator.ingest ordinance.pdf \\
    --jurisdiction "Cambridge, MA" --test T6
extracted 1 rule, quote verified
T6: compare with / without at 2026-10-01 and the effective date</pre>""",
    "end": """<h1>Reproducible</h1><p class=sub>cached model answers · audit log · 17 tests</p>
      <p class=foot>github.com/bisale24-ops/rental-law-navigator · narration synthesized</p>""",
}
