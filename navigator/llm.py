"""One JSON-returning model call, cached on disk so every run after the first is free and reproducible.

The cache key is the model-independent request (prompt + schema), so a rerun replays the recorded answer and
the live demo never depends on model quota. Models are tried in order; a model whose daily quota is spent is
skipped for the rest of the process.
"""
import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "llm_cache"
MODELS = os.environ.get("NAV_MODELS", "gemini-3.6-flash,gemini-3.5-flash,gemini-3.8-flash,gemini-3.7-flash,"
                                      "gemini-3.5-flash-lite").split(",")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_SPENT = set()


class NoModel(RuntimeError):
    pass


def _key():
    v = os.environ.get("GEMINI_API_KEY", "").strip()
    if v:
        return v
    p = pathlib.Path.home() / ".config" / "gemini.key"
    return p.read_text().strip() if p.exists() else ""


PROVIDER = os.environ.get("NAV_PROVIDER", "gemini")          # gemini | anthropic
CLAUDE_MODEL = os.environ.get("NAV_CLAUDE_MODEL", "claude-sonnet-5-5")


def _anthropic_key():
    v = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if v:
        return v
    p = pathlib.Path.home() / ".config" / "anthropic.key"
    return p.read_text().strip() if p.exists() else ""


def _ask_claude(system, prompt, schema, path, tag):
    """Claude with a forced tool call: the tool's input schema is the output schema."""
    body = {"model": CLAUDE_MODEL, "max_tokens": 16000, "temperature": 0, "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"name": "emit", "description": "Return the result.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": "emit"}}
    last = None
    for attempt in range(5):
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json", "x-api-key": _anthropic_key(),
                                              "anthropic-version": "2023-06-01"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=600) as r:   # noqa: S310 - fixed https endpoint
                d = json.load(r)
            out = next(c["input"] for c in d["content"] if c["type"] == "tool_use")
            meta = {"model": d.get("model", CLAUDE_MODEL), "seconds": round(time.time() - t0, 1), "tag": tag,
                    "usage": d.get("usage", {}), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"meta": meta, "output": out}, indent=1))
            return out, dict(meta, cached=False)
        except urllib.error.HTTPError as e:
            last = f"{CLAUDE_MODEL} {e.code} {e.read().decode(errors='replace')[:300]}"
            if e.code in (429, 500, 529, 503):
                time.sleep(10 * (attempt + 1))
                continue
            break
        except (TimeoutError, urllib.error.URLError, StopIteration, KeyError) as e:
            last = f"{CLAUDE_MODEL} {type(e).__name__} {e}"[:300]
            time.sleep(5)
    raise NoModel(last or "claude unavailable")


def ask_json(system, prompt, schema, tag="call", replay_only=False, models=None):
    """Returns (parsed JSON, meta). meta records model, cache hit and timing for the audit log."""
    h = hashlib.sha256(json.dumps([system, prompt, schema], sort_keys=True).encode()).hexdigest()[:24]
    ns = "claude-" if PROVIDER == "anthropic" else ""
    path = CACHE / f"{ns}{tag}-{h}.json"
    if path.exists():
        rec = json.loads(path.read_text())
        return rec["output"], dict(rec["meta"], cached=True)
    if replay_only:
        raise NoModel(f"not recorded: {tag}")
    if PROVIDER == "anthropic":
        return _ask_claude(system, prompt, schema, path, tag)
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                 "responseJsonSchema": schema}}
    key = _key()
    last = None
    for model in [m for m in (models or MODELS) if m not in _SPENT]:
        for attempt in range(5):
            req = urllib.request.Request(URL.format(model=model), data=json.dumps(body).encode(),
                                         headers={"content-type": "application/json", "x-goog-api-key": key})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=300) as r:   # noqa: S310 - fixed https endpoint
                    d = json.load(r)
                text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"]
                               if not p.get("thought"))
                out = json.loads(text)
                meta = {"model": model, "seconds": round(time.time() - t0, 1), "tag": tag,
                        "usage": d.get("usageMetadata", {}), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                CACHE.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"meta": meta, "output": out}, indent=1))
                return out, dict(meta, cached=False)
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")
                last = f"{model} {e.code} {msg[:300]}"
                if e.code == 429 and "PerDay" in msg:
                    _SPENT.add(model)
                    break
                if e.code in (429, 500, 503, 504):
                    time.sleep(min(30, 4 * (attempt + 1)))
                    continue
                break
            except (json.JSONDecodeError, KeyError, IndexError, TimeoutError, urllib.error.URLError) as e:
                last = f"{model} {type(e).__name__} {e}"[:300]
                time.sleep(3)
                continue
    raise NoModel(last or "no model available")
