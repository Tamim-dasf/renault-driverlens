"""
Settings of the Renault ARAT Platform.
Everything you may want to change is in this file. Secrets (API key) live in the .env file.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env_file(path: str) -> None:
    """Read KEY=VALUE lines of the .env file into the environment (no extra library needed)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(os.path.join(BASE_DIR, ".env"))

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
DATA_DIR = os.path.join(BASE_DIR, "our data")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "train_results.csv")
TEST_RESULTS_FILE = os.path.join(RESULTS_DIR, "test_results.csv")
MEMORY_FILE = os.path.join(RESULTS_DIR, "global_memory.json")
SPLIT_FILE = os.path.join(RESULTS_DIR, "split_manifest.json")
# `--dry-run` writes to separate files, so fake results never mix with real ones.
DRY_RUN_RESULTS_FILE = os.path.join(RESULTS_DIR, "dry_run_train_results.csv")
DRY_RUN_MEMORY_FILE = os.path.join(RESULTS_DIR, "dry_run_global_memory.json")
DRY_RUN_TEST_RESULTS_FILE = os.path.join(RESULTS_DIR, "dry_run_test_results.csv")

# ----------------------------------------------------------------------------
# Language model (Gemini). The key and the model ID come from the .env file.
# ----------------------------------------------------------------------------
LLM_CONFIG = {
    "api_key": os.getenv("GEMINI_API_KEY"),
    # Copy the exact model ID from Google AI Studio into .env (GEMINI_MODEL=...).
    "model_name": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
    "default_max_tokens": 2048,
    "default_temperature": 0.5,
    # "low" saves quota on Gemini models. Gemma models do not support it: write
    # GEMINI_THINKING_LEVEL=none in .env to turn it off.
    "thinking_level": (None if os.getenv("GEMINI_THINKING_LEVEL", "low").strip().lower() in ("none", "")
                       else os.getenv("GEMINI_THINKING_LEVEL", "low").strip().lower()),
    "max_retries": 4,
    # Pause between two API calls, to stay under the free-tier rate limit.
    "min_interval_seconds": float(os.getenv("MIN_INTERVAL_SECONDS", "4")),
}

# ----------------------------------------------------------------------------
# Agents
# ----------------------------------------------------------------------------
TOM_CONFIG = {
    # Hypotheses generated per comment. 3 keeps the number of API calls low; raise to 5 later.
    "hypothesis_count_k": 3,
}

DOMAIN_CONFIG = {
    "lambda_weight": 0.6,
    # "domain_rules": {...}  # optional: replaces the French-market rules in domain_agent.py
}

RESPONSE_CONFIG = {
    "beta": 0.8,                  # weight of empathy vs coherence in the utility score
    "utility_threshold": 0.8,     # below this, the response is revised
    "max_revisions": 2,
}

MEMORY_CONFIG = {
    "salt": os.getenv("MEMORY_SALT", "renault-arat"),
    "max_excerpt_chars": 200,
}

# ----------------------------------------------------------------------------
# Run options
# ----------------------------------------------------------------------------
RUN_CONFIG = {
    "sample_size": 20,            # training comments per run; rerun to resume the remaining 60%
    "random_seed": 42,
    "train_fraction": 0.6,
    "test_fraction": 0.4,
    # If the loader labels a file with the wrong car model, correct it here, e.g.
    #   "yt-comments-2026-11-13-12-39-34.xlsx": "Scénic E-Tech",
    "file_car_models": {
    },
    "max_consecutive_errors": 3,  # stop early if the API keeps failing (quota, bad key...)
}
