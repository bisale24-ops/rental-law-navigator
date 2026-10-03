"""Technical walkthrough, under 60 seconds: what was hard, how we got past it, what is still limited."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from vdata import *  # noqa: F401,F403,E402
from look import STYLE  # noqa: E402,F401

VOICE = "en-US-AndrewNeural"
SCENES = [
    ("card:hard1", "Hard part one: models invent quotes. So the model only proposes; code locates every quote in "
                   f"the source. Of {words(PROPOSED)} proposed rules, {words(DROPPED)} were dropped."),
    ("clip:pipeline", "Every decision is in the audit log, and every model answer is cached, so a rerun is exact."),
    ("card:hard2", "Hard part two: the mailing city is not the legal city. The Census Geocoder decides, and a house "
                   "number check caught a Cambridge address placed in Boston."),
    ("card:hard3", "Hard part three: missing facts. Coverage tests are three-valued, so a missing year, or the "
                   "cutoff year itself, is unknown, never a guess."),
    ("card:limits", "Limits: some ordinances sit on sites that forbid crawling, so they are listed for human "
                    "review, and free model quotas capped how many passes we could run. The narration is synthesized."),
]
CLIPS = {"pipeline": ("clips/pipeline.webm", 0)}
CARDS = {
    "hard1": f"""<h1>1 · Models invent quotes</h1><table>
      <tr><td>Rules proposed by the model</td><td class=big>{PROPOSED}</td></tr>
      <tr><td>Quote found verbatim by code</td><td class="big ok">{EXACT}</td></tr>
      <tr><td>Repaired to the source's exact words</td><td class=big>{REPAIRED}</td></tr>
      <tr><td>Dropped: quote not in the source</td><td class="big warn">{DROPPED}</td></tr></table>""",
    "hard2": """<h1>2 · Mailing city ≠ legal city</h1><table>
      <tr><td>Dorchester, Roxbury, Van Nuys</td><td class=d>Census Geocoder → incorporated place</td></tr>
      <tr><td>322-322.5 Western Ave, Cambridge</td><td class=warn>matched “5 Western Ave”, Boston → number mismatch → Cambridge</td></tr>
      <tr><td>No unit count</td><td class=ok>NJ class 4C → 5+ units; “3S-F-D-6U” → 6</td></tr></table>""",
    "hard3": """<h1>3 · Facts the record lacks</h1><table>
      <tr><td>Built 1979, cutoff June 13, 1979</td><td class=warn>unknown</td></tr>
      <tr><td>No year built (San Diego, Berkeley)</td><td class=warn>unknown, missing fact named</td></tr>
      <tr><td>Owner-based exemption, 20-unit building</td><td class=ok>cannot apply → applies</td></tr>
      <tr><td>State cap where city rent control applies</td><td class=d>superseded</td></tr></table>""",
    "limits": """<h1>Remaining limits</h1><table>
      <tr><td>Code publishers that forbid crawling</td><td class=d>not fetched; listed for human review</td></tr>
      <tr><td>Free-tier model quotas</td><td class=d>fewer reading passes than we wanted</td></tr>
      <tr><td>Year built ≠ certificate date</td><td class=d>cutoff years stay unknown</td></tr></table>
      <p class=foot>github.com/bisale24-ops/rental-law-navigator · MIT · narration synthesized</p>""",
}
