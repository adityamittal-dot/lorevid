"""Scene illustrations, tried in order (IMAGE_BACKENDS, comma-separated):
  cloudflare   - Workers AI Flux-1-schnell, ~170 free images/day (CF_ACCOUNT_ID + CF_API_TOKEN)
  pollinations - free Flux API, slower, rate-limited (optional POLLINATIONS_TOKEN)
  local        - your own NVIDIA GPU via diffusers
If one fails or runs out of quota, the next one is used.
"""
import base64, os, time, urllib.parse
import requests

_dead = set()   # backends out of quota for this run
_down = {}      # backend -> time it failed completely; skipped for COOLDOWN s so the next backend is tried at once
COOLDOWN = int(os.getenv("IMAGE_BACKEND_COOLDOWN", "600"))
_pipe = None


def full_prompt(scene, plan):
    looks = {c["id"]: c["look"] for c in plan.get("characters", [])}
    who = "; ".join(looks[c] for c in scene.get("characters", []) if c in looks)
    parts = [scene["image_prompt"], f"Characters: {who}" if who else "", plan.get("era_setting", ""),
             plan["style"], "no text, no watermark, no captions, no gore, no nudity"]
    return ". ".join(p for p in parts if p)


def _cloudflare(prompt, out, seed, w, h):
    acct, tok = os.getenv("CF_ACCOUNT_ID"), os.getenv("CF_API_TOKEN")
    if not (acct and tok):
        raise RuntimeError("no Cloudflare credentials")
    orient = "vertical portrait composition" if h > w else "wide landscape composition, subject centered"
    r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"prompt": f"{prompt}. {orient}"[:2000], "steps": 4, "seed": seed}, timeout=120)
    if r.status_code == 429 or "neuron" in r.text.lower() and r.status_code >= 400:
        _dead.add("cloudflare")
        raise RuntimeError("Cloudflare daily quota used up")
    r.raise_for_status()
    open(out, "wb").write(base64.b64decode(r.json()["result"]["image"]))


def _pollinations(prompt, out, seed, w, h):
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1800])
    params = {"width": w, "height": h, "seed": seed, "model": os.getenv("POLLINATIONS_MODEL", "flux"), "nologo": "true"}
    headers = {"Authorization": f"Bearer {os.environ['POLLINATIONS_TOKEN']}"} if os.getenv("POLLINATIONS_TOKEN") else {}
    tries = int(os.getenv("POLLINATIONS_TRIES", "6"))
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=180)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                open(out, "wb").write(r.content)
                time.sleep(3)
                return
            print(f"  pollinations {r.status_code}, waiting", flush=True)
        except requests.RequestException as e:
            print(f"  pollinations error {e}", flush=True)
        if attempt < tries - 1:
            time.sleep(min(20 * (attempt + 1), 120))
    raise RuntimeError("Pollinations failed")


def _local(prompt, out, seed, w, h):
    global _pipe
    import torch
    from diffusers import AutoPipelineForText2Image
    model = os.getenv("LOCAL_MODEL", "stabilityai/sdxl-turbo")
    if _pipe is None:
        _pipe = AutoPipelineForText2Image.from_pretrained(model, torch_dtype=torch.float16, variant="fp16").to("cuda")
    turbo = "turbo" in model
    _pipe(prompt=prompt[:600], width=w, height=h, num_inference_steps=4 if turbo else 28,
          guidance_scale=0.0 if turbo else 6.0,
          generator=torch.Generator("cuda").manual_seed(seed)).images[0].save(out)


BACKENDS = {"cloudflare": _cloudflare, "pollinations": _pollinations, "local": _local}


def generate(prompt, out, seed, w=1344, h=768):
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return
    order = [b.strip() for b in os.getenv("IMAGE_BACKENDS", "pollinations,cloudflare").split(",")]
    for b in order:
        if b in _dead or time.time() - _down.get(b, 0) < COOLDOWN:
            continue
        try:
            BACKENDS[b](prompt, out, seed, w, h)
            _down.pop(b, None)
            return
        except Exception as e:
            print(f"  {b} failed: {e}", flush=True)
            _down[b] = time.time()
    raise RuntimeError("All image backends failed (is CF_API_TOKEN set? run the check-setup workflow)")
