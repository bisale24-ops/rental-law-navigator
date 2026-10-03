# Rental Law Navigator

**Which housing rules apply at this address on this date, and why.** It reads a corpus of state and city law, turns
each rule into a structured record (Module A), resolves 500 apartment addresses to their legal jurisdiction and
tests every rule's coverage conditions (Module B), and re-answers when the law changes (Module C). Every answer
names its source, quotes it verbatim and shows the retrieval date.

> Not legal advice and not a compliance certification. A research prototype on public data.

MIT Hack-Nation · Challenge 02 (RealPage) · KHLab

## What makes the answers trustworthy

| Guarantee | How |
|---|---|
| No invented quotes | The model proposes rules, but code has the last word. Each `quoted_span` must appear in the source text after whitespace and quote normalization. A near-miss (≥ 92% similar) is replaced with the source's own words. Anything else is dropped and logged. |
| The real city, not the mailing city | The Census Geocoder places each address inside an incorporated place. A match whose house number differs from the input is not trusted. That check caught "322-322.5 Western Ave, Cambridge", which had been matched to a Harvard building in Boston. |
| "Unknown" instead of a guess | Coverage tests are three-valued. A building built in a cutoff year is unknown, because year built is not the certificate-of-occupancy date. A missing year or unit count is unknown, and the answer names the missing fact. |
| Facts the record does have, used | Unit counts come from the assessor count when present. Otherwise they come from the use code: "Five or more apartments" means 5+; NJ class 4C means 5+; Boston land use "A" means 7+; "3S-F-D-6U-NH" means 6. |
| Layers of law | A state cap that yields to stricter local law is reported as `superseded` where the local rule applies. Where the local rule's coverage is unknown, the state cap is `unknown` too. |
| Conflicts go to a human | A state law that may preempt city ordinances flags every affected address, for example the NJ FAIR Act vs. the Jersey City and Hoboken bans. So do sources that disagree on a date or number. |
| Enacted vs. not law | Pending bills are `pending`. Failed measures are recorded as `failed` and never reported as rules: the MA rent-control ballot question struck in June 2026 yields no rent cap anywhere. |
| Reproducible | Every model answer is cached on disk. A rerun replays the cache exactly and costs nothing. `out/audit.jsonl` logs every extraction decision, lookup and change test. |

## Run it

```bash
python3 -m navigator.web                 # UI at http://127.0.0.1:8801 (no dependencies beyond Python 3.11+)
python3 -m navigator.run                 # out/lookups.json + out/changes.json, as of 2026-10-01
python3 -m navigator.run --as-of 2027-07-02
python3 -m unittest discover tests
```

Rebuilding from the corpus needs a model key. It uses Gemini on the free tier, or Claude with `NAV_PROVIDER=anthropic`.

```bash
python3 tools/geocode.py                 # Census Geocoder -> data/geocode.json
python3 tools/capture_links.py           # link-only pages, only where robots.txt allows (see Sources)
python3 -m navigator.extract             # Module A: two reading passes per document, quote check
python3 -m navigator.coverage            # coverage statements ("units first occupied after June 13, 1979 ...")
python3 -m navigator.consolidate         # one record per jurisdiction x category, conflicts, no-rule findings
python3 -m navigator.run                 # Modules B and C
```

A new law, such as the hour-16 change case, takes one command. Nothing about it is hand-coded.

```bash
python3 -m navigator.ingest ordinance.pdf --jurisdiction "Cambridge, MA" --test T6 --title "..."
```

The document goes through the same extraction and quote check. The change case is answered by comparing every
address with and without the rules this document contributed, at the query date and at the new rule's effective
date.

## Submission files

- `out/rules.json`: rule records in the supplied schema, plus `no_rule_findings`. These cover every
  jurisdiction × category with no enacted rule: what was searched, what governs instead, and which link-only
  sources could hold one.
- `out/lookups.json`: all 500 addresses, as of 2026-10-01.
- `out/changes.json`: T1–T5, plus T6 once ingested.

## Sources

The starter-pack corpus comes first. Some laws were link-only in the pack, pointing to code publishers. For
those, `tools/capture_links.py` fetched official government copies one page at a time, honouring robots.txt
(RFC 9309), and kept URL, time and sha256 (`data/supplement/`). Examples: Hoboken's Chapter 155 notices, Newark's
rent-control FAQ, Jersey City's Rent Leveling rules, the San Diego Municipal Code, and NJ statutes from nj.gov.
These records are marked `team capture`. Publishers whose robots.txt disallows crawling (ecode360, American
Legal, Justia) were not fetched; their rules are listed for human review.

## Layout

```
navigator/  extract.py coverage.py consolidate.py   Module A
            facts.py engine.py                      Module B (pure code)
            run.py ingest.py                        Module C
            llm.py audit.py web.py page.html
tools/      geocode.py capture_links.py
data/       geocode.json candidates.json rules_full.json llm_cache/ supplement/
out/        rules.json lookups.json changes.json audit.jsonl
```
