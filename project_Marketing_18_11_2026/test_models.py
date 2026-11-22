"""
Finds which Gemini Flash and Gemma models answer quickly with YOUR key.

Run it from the 'real project' folder:   python test_models.py
It lists the models your key can use, sends each one a tiny message (20 s limit),
and tells you which ID to copy into the .env file.
"""
import time

from google import genai
from google.genai import types

import config

key = config.LLM_CONFIG.get("api_key")
if not key:
    raise SystemExit("No GEMINI_API_KEY found. Check your .env file.")

client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=20000))  # 20 s

SKIP_WORDS = ("image", "tts", "live", "audio", "embed", "robotics", "computer-use", "native")


def can_generate_text(model) -> bool:
    actions = getattr(model, "supported_actions", None) or getattr(model, "supported_generation_methods", None)
    return actions is None or "generateContent" in actions


names = []
for m in client.models.list():
    name = m.name.replace("models/", "")
    lowered = name.lower()
    if ("flash" in lowered or "gemma" in lowered) and can_generate_text(m) and not any(w in lowered for w in SKIP_WORDS):
        names.append(name)
names = sorted(set(names))[:16]

if not names:
    raise SystemExit("No Flash or Gemma model found for this key.")

print(f"Testing {len(names)} model(s), up to 20 s each...\n")
working = []
for name in names:
    start = time.time()
    try:
        reply = client.models.generate_content(model=name, contents="Reply with the word OK only.")
        seconds = time.time() - start
        working.append((seconds, name))
        print(f"  OK    {seconds:5.1f} s   {name}   -> {(reply.text or '').strip()[:20]!r}")
    except Exception as e:
        print(f"  FAIL  {time.time() - start:5.1f} s   {name}   -> {str(e)[:80]}")

print()
if working:
    best = min(working)[1]
    print(f"Fastest working model: {best}")
    print(f"  -> .env:   GEMINI_MODEL={best}")
    print("  (Gemini Flash models have small free daily limits: check the Rate Limit page.)")

    gemma = sorted(w for w in working if "gemma" in w[1].lower())
    if gemma:
        print()
        print(f"Best Gemma model: {gemma[0][1]}   (Gemma has a much bigger free daily limit)")
        print("  -> .env:   GEMINI_MODEL=" + gemma[0][1])
        print("             GEMINI_THINKING_LEVEL=none")
else:
    print("No model answered in time. Wait 15 to 30 minutes and run this script again.")