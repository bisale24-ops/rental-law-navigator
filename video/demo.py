"""Product demo, under 60 seconds. Real recordings of the app; synthesized narration."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from vdata import *  # noqa: F401,F403,E402
from look import STYLE  # noqa: E402,F401

VOICE = "en-US-AndrewNeural"
SCENES = [
    ("clip:lookup", "Pick any of five hundred buildings. Los Angeles, built nineteen twenty seven: the state rent "
                    "cap is superseded by the city's rent stabilization. Every answer says why, and quotes the law."),
    ("clip:jersey", "Jersey City. The state FAIR Act is enacted but not yet effective, and it may preempt the "
                    "city's algorithm ban, so both are flagged for a human, not decided by us."),
    ("clip:timetravel", "Change the date and the answer changes. California's algorithm law is not yet "
                        "effective on December thirty first, and applies two days later."),
    ("clip:spanish", "Tenants can read it in Spanish. The quoted law stays in the original."),
    ("clip:changes", "Every change case runs through the same engine, including the struck ballot "
                     "question: no rent cap anywhere in Massachusetts."),
    ("card:end", "Not legal advice. The narration is synthesized."),
]
CARDS = {"end": """<h1>Rental Law Navigator</h1><p class=sub>khlab-rental-law-navigator.onrender.com</p>
  <p class=foot>Not legal advice · narration synthesized · KHLab</p>"""}
CLIPS = {k: (f"clips/{k}.webm", 0) for k in ("lookup", "jersey", "timetravel", "spanish", "changes")}
