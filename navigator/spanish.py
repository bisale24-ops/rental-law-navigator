"""Spanish view. Rule titles and plain-language requirements are translated once by a model and cached in
data/translations_es.json; the explanations the engine writes are translated by fixed patterns, so numbers,
dates and rule ids are never retyped by a model. Quotes stay in the original English: they are the law's words.

    python3 -m navigator.spanish        # (re)build data/translations_es.json
"""
import json
import pathlib
import re

from .llm import ask_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "translations_es.json"

SYSTEM = ("Translate rental-housing rule summaries from English to clear, neutral Latin American Spanish for "
          "tenants and small landlords. Keep numbers, dollar amounts, dates, percentages, code citations and proper "
          "names exactly as given. Do not add or drop facts. Plain words, short sentences.")
SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "title": {"type": "string"}, "requirement": {"type": "string"},
    "key_value": {"type": ["string", "null"]}, "coverage": {"type": ["string", "null"]}},
    "required": ["id", "title", "requirement", "key_value", "coverage"]}}}, "required": ["items"]}


def key(r):
    """Translations follow the text, not the id: rule ids change when the corpus grows."""
    return f"{r['title']}\n{r['requirement']}"


def build(rules):
    out = load()
    todo = [r for r in rules if key(r) not in out]
    for i in range(0, len(todo), 20):
        part = todo[i:i + 20]
        chunk = [{"id": str(n), "title": r["title"], "requirement": r["requirement"], "key_value": r["key_value"],
                  "coverage": (r.get("coverage") or {}).get("summary")} for n, r in enumerate(part)]
        res, _ = ask_json(SYSTEM, json.dumps(chunk, ensure_ascii=False), SCHEMA, tag="spanish")
        for it in res["items"]:
            if it["id"].isdigit() and int(it["id"]) < len(part):
                out[key(part[int(it["id"])])] = it
    PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def load():
    return json.loads(PATH.read_text()) if PATH.exists() else {}


def rule_es(view, rule, table):
    t = table.get(key(rule))
    if not t:
        return view
    return dict(view, title=t["title"], requirement=t["requirement"], key_value=t["key_value"] or view.get("key_value"),
                coverage=t.get("coverage") or view.get("coverage"), translated=True)


# engine explanations -> Spanish, by pattern; anything unmatched stays English rather than being guessed
PATTERNS = [
    (r"^built (\d{4}), before the ([\d-]+) cutoff$", r"construido en \1, antes de la fecha límite \2"),
    (r"^built (\d{4}), after the ([\d-]+) cutoff$", r"construido en \1, después de la fecha límite \2"),
    (r"^built in (\d{4}), the cutoff year; the (.+) date decides and is not in the record$",
     r"construido en \1, el año límite; decide la fecha de \2, que no está en el registro"),
    (r"^coverage depends on the (.+) date \((on or before|after) ([\d-]+)\) and the record has no year built$",
     r"la cobertura depende de la fecha de \1 (\2 \3) y el registro no tiene año de construcción"),
    (r"^built (\d{4}), more than (\d+) years before the query date$",
     r"construido en \1, más de \2 años antes de la fecha de consulta"),
    (r"^built (\d{4}), less than (\d+) years before the query date$",
     r"construido en \1, menos de \2 años antes de la fecha de consulta"),
    (r"^covers buildings more than (\d+) years old; the record has no year built$",
     r"cubre edificios de más de \1 años; el registro no tiene año de construcción"),
    (r"^(\d+)\+ units \((.+)\), at least the (\d+) required$", r"\1 o más unidades (\2), al menos las \3 requeridas"),
    (r"^covers buildings with (\d+)\+ units and the record does not say how many units \((.+)\)$",
     r"cubre edificios con \1 o más unidades y el registro no dice cuántas tiene (\2)"),
    (r"^the owner-based exemption only reaches buildings of (\d+) units or fewer; this one has (.+)$",
     r"la exención por tipo de propietario solo alcanza edificios de \1 unidades o menos; este tiene \2"),
    (r"^coverage depends on the owner \((.+)\); owner data is deliberately not in the public record$",
     r"la cobertura depende del propietario (\1); los datos del propietario no están en el registro público"),
    (r"^covers residential rentals in the jurisdiction; no size or age limit stated$",
     "cubre los alquileres residenciales de la jurisdicción; no indica límite de tamaño ni de antigüedad"),
    (r"^a statewide limit on what cities may regulate; it applies to every address in the state$",
     "un límite estatal a lo que pueden regular las ciudades; aplica a todas las direcciones del estado"),
    (r"^a bill or proposal, not law, as of ([\d-]+)$", r"un proyecto o propuesta, no es ley, al \1"),
    (r"^enacted; takes effect ([\d-]+), after the query date$",
     r"aprobada; entra en vigor el \1, después de la fecha de consulta"),
    (r"^covered, but the local rule (\S+) \((.+)\) governs here$",
     r"cubierto, pero aquí rige la norma local \1 (\2)"),
    (r"^applies unless the local rule (\S+) covers the unit, and that rule's coverage is unknown$",
     r"aplica salvo que la norma local \1 cubra la unidad, y esa cobertura es desconocida"),
    (r"^possible conflict: (.+) may preempt (.+); flagged for human review$",
     r"posible conflicto: \1 podría prevalecer sobre \2; marcado para revisión humana"),
    (r"^also depends on: (.+) \(not in the property record\)$", r"también depende de: \1 (no está en el registro)"),
    (r"^subsidized units may be exempt and the record says '(.+)'$",
     r"las unidades subsidiadas pueden estar exentas y el registro dice '\1'"),
    (r"^Census Geocoder: matched '(.+)' inside (.+)$", r"Geocodificador del Censo: '\1' dentro de \2"),
]


def reason(text):
    for pat, rep in PATTERNS:
        if re.match(pat, text):
            return re.sub(pat, rep, text)
    return text


if __name__ == "__main__":
    rules = json.loads((ROOT / "data" / "rules_full.json").read_text())
    print(len(build(rules)), "rules translated")
