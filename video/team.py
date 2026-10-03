"""Team introduction, under 60 seconds. Voice is synthesized; no presenter on camera."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from vdata import *  # noqa: F401,F403,E402
from look import STYLE  # noqa: E402,F401

VOICE = "en-US-AndrewNeural"
SCENES = [
    ("card:who", "We are KHLab, a one-person software lab in Bishkek, Kyrgyzstan. I am Aleksandr Khrukalo."),
    ("card:why", "Before writing software I worked as a legal specialist at a law firm, so a statute, a "
                 "citation and the word unknown mean something to me. Since then I have shipped Android apps, "
                 "Python tools and AI agents, and I build for one thing: answers you can check."),
    ("card:what", "For RealPage's challenge we built the Rental Law Navigator. It reads the law, resolves every "
                  "address to its real city, and tells you which rules apply, on which date, and why, with the "
                  "source quoted word for word."),
    ("card:bye", "Why us: we treat a legal answer like a test result, reproducible and sourced. The narration is synthesized."),
]
CARDS = {
    "who": """<h1>KHLab</h1><p class=sub>One-person software lab · Bishkek, Kyrgyzstan</p>
      <div class=big>Aleksandr Khrukalo</div><p class=foot>Solo entry · Hack-Nation 7th Global AI Hackathon</p>""",
    "why": """<h1>Law first, then code</h1><table>
      <tr><td>Legal specialist at a law firm</td><td class=d>statutes, citations, “it depends”</td></tr>
      <tr><td>Android apps, Python tools, AI agents</td><td class=d>shipped, in stores and on GitHub</td></tr>
      <tr><td>What we optimize for</td><td class=ok>answers you can check</td></tr></table>""",
    "what": """<h1>Rental Law Navigator</h1><p class=sub>Challenge 02 · RealPage</p><table>
      <tr><td>Reads the law</td><td class=d>""" + f"{DOCS} documents, every quote verified" + """</td></tr>
      <tr><td>Finds the real city</td><td class=d>Census Geocoder, 500 addresses</td></tr>
      <tr><td>Answers with a date and a reason</td><td class=d>applies · unknown · superseded · not yet effective · pending</td></tr></table>""",
    "bye": """<h1>Thank you</h1><p class=sub>github.com/bisale24-ops/rental-law-navigator</p>
      <p class=foot>Not legal advice. Narration synthesized.</p>""",
}
