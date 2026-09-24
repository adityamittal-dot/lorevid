"""LLM access.
Primary: Claude (Opus 5.5) through the Message Batches API (50% cheaper). Falls back to the normal
Claude API if a batch is slow, and to free Gemini after CLAUDE_UNTIL or when credits run out.
Every call is appended to costs.csv."""
import csv, datetime, json, os, re, time
import requests

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_UNTIL = os.getenv("CLAUDE_UNTIL", "2026-11-10")          # credits expire
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0)}  # $/MTok
BATCH_WAIT_MIN = int(os.getenv("BATCH_WAIT_MIN", "120"))
API = "https://api.anthropic.com/v1"


def _hdr():
    return {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
            "content-type": "application/json"}


def _log(step, model, usage, batch):
    pin, pout = PRICES.get(model, (0, 0))
    cost = (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1e6
    if batch:
        cost /= 2
    new = not os.path.exists("costs.csv")
    with open("costs.csv", "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "step", "model", "batch", "input_tokens", "output_tokens", "usd"])
        w.writerow([datetime.datetime.utcnow().isoformat(timespec="seconds"), step, model, batch,
                    usage.get("input_tokens", 0), usage.get("output_tokens", 0), f"{cost:.4f}"])
    print(f"  [{step}] {model}{' batch' if batch else ''}: {usage.get('input_tokens')} in / "
          f"{usage.get('output_tokens')} out = ${cost:.3f}")


def _text(msg):
    return "".join(b.get("text", "") for b in msg["content"] if b.get("type") == "text")


def _claude_batch(params, step):
    r = requests.post(f"{API}/messages/batches", headers=_hdr(),
                      json={"requests": [{"custom_id": "x", "params": params}]}, timeout=60)
    r.raise_for_status()
    bid = r.json()["id"]
    print(f"  batch {bid} submitted, waiting...")
    t0 = time.time()
    while time.time() - t0 < BATCH_WAIT_MIN * 60:
        time.sleep(20)
        b = requests.get(f"{API}/messages/batches/{bid}", headers=_hdr(), timeout=60).json()
        if b.get("processing_status") == "ended":
            for line in requests.get(b["results_url"], headers=_hdr(), timeout=120).text.splitlines():
                res = json.loads(line)["result"]
                if res["type"] == "succeeded":
                    _log(step, params["model"], res["message"]["usage"], True)
                    return _text(res["message"])
                raise RuntimeError(f"batch result: {res}")
    requests.post(f"{API}/messages/batches/{bid}/cancel", headers=_hdr(), timeout=60)
    raise TimeoutError("batch too slow")


def _claude_direct(params, step):
    for attempt in range(4):
        r = requests.post(f"{API}/messages", headers=_hdr(), json=params, timeout=900)
        if r.status_code in (429, 500, 529):
            time.sleep(30 * (attempt + 1)); continue
        r.raise_for_status()
        m = r.json()
        _log(step, params["model"], m["usage"], False)
        return _text(m)
    raise RuntimeError("Claude API kept failing")


def _gemini(prompt, system, step):
    key = os.environ["GEMINI_API_KEY"]
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}}
    for attempt in range(6):
        r = requests.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                          headers={"Authorization": f"Bearer {key}"}, json=body, timeout=600)
        if r.status_code in (429, 500, 503):
            time.sleep(20 * (attempt + 1)); continue
        r.raise_for_status()
        j = r.json()
        _log(step, model, {"input_tokens": j.get("usage", {}).get("prompt_tokens", 0),
                           "output_tokens": j.get("usage", {}).get("completion_tokens", 0)}, False)
        return j["choices"][0]["message"]["content"]
    raise RuntimeError("Gemini kept failing")


def _use_claude():
    return bool(os.getenv("ANTHROPIC_API_KEY")) and datetime.date.today().isoformat() < CLAUDE_UNTIL


def chat(prompt, system, step="llm", max_tokens=16000):
    if _use_claude():
        params = {"model": CLAUDE_MODEL, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": prompt}]}
        try:
            if os.getenv("CLAUDE_BATCH", "1") == "1":
                try:
                    return _claude_batch(params, step)
                except TimeoutError:
                    print("  batch slow, using direct API")
            return _claude_direct(params, step)
        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else ""
            print(f"  Claude error {body[:200]}")
            if not os.getenv("GEMINI_API_KEY"):
                raise
            print("  falling back to Gemini")
    return _gemini(prompt, system, step)


def parse_json(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw[raw.find("{"): raw.rfind("}") + 1])


def chat_json(prompt, system, step="llm", max_tokens=16000):
    for attempt in range(3):
        try:
            return parse_json(chat(prompt, system, step, max_tokens))
        except (json.JSONDecodeError, ValueError):
            print("  invalid JSON, retrying")
    raise RuntimeError("LLM did not return valid JSON")
