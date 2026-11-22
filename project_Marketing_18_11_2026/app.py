"""
DriverLens Platform dashboard (adapted from MetaMind's Flask app).

Shows the training results saved by main.py as an interactive dashboard,
and lets you analyze one new comment live.

Usage (from the 'real project' folder):
    python app.py            then open http://127.0.0.1:5000
    python app.py --mock     live analysis with the FAKE model (no API key, instant)
"""
import argparse
import glob
import json
import os
import random
import threading
import time
import uuid

import pandas as pd
from flask import Flask, jsonify, render_template, request

import config
from utils import build_result_row, clean_comment_text, load_comments, remove_user_mentions

app = Flask(__name__)

CAR_MODELS = ["Renault 5 E-Tech", "Mégane E-Tech", "Scénic E-Tech", "Renault 4 E-Tech", "Other"]
MAX_COMMENT_CHARS = 1000

LLM_MODE = "auto"            # "auto" (Gemini if a key exists, else fake), or "mock"
_pipeline = None             # built on the first live analysis
_pipeline_lock = threading.Lock()
_pool_cache = None           # size of the full dataset, computed once

# Live analyses run in a background thread; the browser polls their progress.
# job_id -> {"stage": 0-3, "done": bool, "result": dict|None, "error": str|None, "created": time}
_jobs = {}
_jobs_lock = threading.Lock()
JOB_TTL_SECONDS = 15 * 60   # forget finished/abandoned analyses after this delay


def _memory_stamp():
    try:
        stat = os.stat(config.MEMORY_FILE)
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def load_results():
    """Real results if they exist, otherwise the dry-run (fake) ones, otherwise nothing."""
    for path, source in ((config.RESULTS_FILE, "real"), (config.DRY_RUN_RESULTS_FILE, "demo")):
        if os.path.exists(path):
            df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
            df = df[df["error"] == ""]
            if len(df):
                return df, source
    return None, "none"


def get_test_pool():
    """Return held-out comments that have not yet been successfully tested."""
    if not os.path.exists(config.SPLIT_FILE):
        raise FileNotFoundError("Run the training phase once to create the saved train/test split.")
    with open(config.SPLIT_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assignments = manifest.get("assignments", {})
    data = load_comments(config.DATA_DIR, file_car_models=config.RUN_CONFIG["file_car_models"])
    test_rows = data[data["comment_id"].astype(str).map(lambda cid: assignments.get(cid) == "test")].copy()

    train_ids = {cid for cid, split in assignments.items() if split == "train"}
    train_done = set()
    if os.path.exists(config.RESULTS_FILE):
        train_rows = pd.read_csv(config.RESULTS_FILE, dtype=str, encoding="utf-8-sig").fillna("")
        if "error" in train_rows.columns:
            train_rows = train_rows[train_rows["error"] == ""]
        train_done = set(train_rows["comment_id"].dropna().astype(str))
    if not train_done or train_done - train_ids:
        raise ValueError("Complete at least one valid training analysis before using the test comments.")

    from memory import SocialMemory
    memory = SocialMemory(config.MEMORY_CONFIG)
    if not memory.load(config.MEMORY_FILE):
        raise ValueError("The saved global training memory is missing. Run the training phase first.")
    if memory.get_global_stats()["total_comments"] != len(train_done):
        raise ValueError("The saved training memory is out of date. Run the training phase to synchronize it.")

    from main import test_results_for_training_snapshot
    current_results = test_results_for_training_snapshot(config.TEST_RESULTS_FILE, train_done)
    result_files = set(glob.glob(os.path.join(config.RESULTS_DIR, "test_results*.csv")))
    result_files.add(current_results)
    tested_ids = set()
    for path in result_files:
        if not os.path.exists(path):
            continue
        rows = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
        if "comment_id" in rows.columns:
            if "error" in rows.columns:
                rows = rows[rows["error"] == ""]
            tested_ids.update(rows["comment_id"].astype(str))

    test_rows = test_rows[~test_rows["comment_id"].astype(str).isin(tested_ids)]
    counts = {str(model): int(count) for model, count in test_rows["car_model"].value_counts().items()}
    return test_rows, current_results, counts


def get_pool():
    """Number of comments in the full dataset (for 'sample of N')."""
    global _pool_cache
    if _pool_cache is None:
        try:
            data = load_comments(config.DATA_DIR, file_car_models=config.RUN_CONFIG["file_car_models"])
            _pool_cache = {"total": int(len(data)),
                           "by_model": {k: int(v) for k, v in data["car_model"].value_counts().items()}}
        except Exception:
            _pool_cache = {}
    return _pool_cache


def using_mock() -> bool:
    return LLM_MODE == "mock" or not config.LLM_CONFIG.get("api_key")


def analyzer_label() -> str:
    if using_mock():
        return "Demo model (fake answers)"
    return f"Gemini ({config.LLM_CONFIG['model_name']})"


# ----------------------------------------------------------------------------
# Live analysis pipeline
# ----------------------------------------------------------------------------
def get_pipeline():
    global _pipeline
    if _pipeline is None:
        from agents import ToMAgent, DomainAgent, ResponseAgent
        from memory import SocialMemory
        if using_mock():
            from llm_interface import MockLLM
            llm = MockLLM()
        else:
            from llm_interface import GeminiLLM
            llm = GeminiLLM(config.LLM_CONFIG)
        memory = SocialMemory(config.MEMORY_CONFIG)
        memory.load(config.MEMORY_FILE)  # live analysis reads the trained global memory, but never updates it
        _pipeline = {
            "memory": memory,
            "memory_stamp": _memory_stamp(),
            "tom": ToMAgent(config.TOM_CONFIG, llm, memory),
            "domain": DomainAgent(config.DOMAIN_CONFIG, llm, memory),
            "responder": ResponseAgent(config.RESPONSE_CONFIG, llm),
        }
    elif _pipeline["memory_stamp"] != _memory_stamp():
        # Pick up a newly built or incrementally updated training memory without restarting Flask.
        from memory import SocialMemory
        memory = SocialMemory(config.MEMORY_CONFIG)
        memory.load(config.MEMORY_FILE)
        _pipeline["memory"] = memory
        _pipeline["memory_stamp"] = _memory_stamp()
        _pipeline["tom"].social_memory = memory
        _pipeline["domain"].social_memory = memory
    return _pipeline


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    df, source = load_results()
    rows = [] if df is None else df.to_dict(orient="records")
    try:
        _, _, test_counts = get_test_pool()
        test_pool_error = ""
    except Exception as e:
        test_counts = {}
        test_pool_error = str(e)
    return jsonify({
        "source": source,
        "rows": rows,
        "pool": get_pool(),
        "test_counts": test_counts,
        "test_pool_error": test_pool_error,
        "analyzer": analyzer_label(),
        "car_models": CAR_MODELS,
    })


@app.route("/api/test-pick")
def api_test_pick():
    try:
        candidates, _, counts = get_test_pool()
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    model = request.args.get("car_model", "")
    if model and model != "All models":
        candidates = candidates[candidates["car_model"].astype(str) == model]
    if candidates.empty:
        return jsonify({"error": "No unanalysed test comments remain for this model.",
                        "test_counts": counts}), 404
    row = candidates.sample(n=1).iloc[0].to_dict()
    return jsonify({"comment_id": str(row["comment_id"]),
                    "comment": remove_user_mentions(str(row["comment"])),
                    "car_model": str(row["car_model"]),
                    "test_counts": counts})


@app.route("/api/test-status")
def api_test_status():
    try:
        _, _, counts = get_test_pool()
        return jsonify({"test_counts": counts})
    except Exception as e:
        return jsonify({"error": str(e), "test_counts": {}}), 400


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    payload = request.get_json(silent=True) or {}
    comment = remove_user_mentions(clean_comment_text(payload.get("comment", "")))
    if len(comment) < 8:
        return jsonify({"error": "Please write a comment of at least 8 characters."}), 400
    try:
        hypothesis_count = int(payload.get("hypothesis_count", config.TOM_CONFIG.get("hypothesis_count_k", 3)))
    except (TypeError, ValueError):
        return jsonify({"error": "Choose a valid number of hypotheses (2 to 5)."}), 400
    if hypothesis_count not in (2, 3, 4, 5):
        return jsonify({"error": "Choose a valid number of hypotheses (2 to 5)."}), 400
    car_model = payload.get("car_model")
    if car_model not in CAR_MODELS:
        car_model = "Other"

    item = {"comment_id": "live", "car_model": car_model, "comment": comment[:MAX_COMMENT_CHARS],
            "likes": None, "parent_comment": None, "video_title": None}
    test_comment_id = payload.get("test_comment_id")

    class AnalysisRejected(Exception):
        """A problem with the request itself (shown to the user as-is)."""

    def run_analysis(on_stage):
        """The full live analysis; on_stage(1|2|3) is called when each agent starts."""
        from main import process_comment
        item_to_run = item
        with _pipeline_lock:  # one analysis at a time: protects the API rate limit
            test_results_file = None
            if test_comment_id:
                candidates, test_results_file, _ = get_test_pool()
                matches = candidates[candidates["comment_id"].astype(str) == str(test_comment_id)]
                if matches.empty:
                    raise AnalysisRejected("This test comment is no longer available. Pick another one.")
                item_to_run = matches.iloc[0].to_dict()
                if (remove_user_mentions(str(item_to_run["comment"])) != comment
                        or str(item_to_run["car_model"]) != str(car_model)):
                    raise AnalysisRejected("The selected test comment does not match the submitted text.")
            pipe = get_pipeline()
            pipe["tom"].hypothesis_count_k = hypothesis_count
            selected, response = process_comment(item_to_run, pipe["tom"], pipe["domain"], pipe["responder"],
                                                 pipe["memory"], user_id=f"live_{uuid.uuid4().hex[:8]}",
                                                 on_stage=on_stage)
            row = build_result_row(item_to_run, selected, response)
            row["evidence"] = selected.get("evidence", "")
            row["agent_trace"] = {
                "hypothesis_count": hypothesis_count,
                "initial_hypotheses": selected.get("initial_hypotheses", []),
                "refined_hypotheses": selected.get("candidate_hypotheses", []),
                "selected_hypothesis_id": selected.get("id"),
                "response": {
                    "initial_response": response.get("initial_response", {}),
                    "revision_trace": response.get("revision_trace", []),
                    "final_response": {"action": response.get("action"),
                                       "churn_risk": response.get("churn_risk"),
                                       "message": response.get("message")},
                    "final_validation": response.get("validation", {}),
                },
            }
            if test_results_file:
                from utils import append_result
                append_result(test_results_file, row)
        return row

    # Run the analysis in a background thread. The browser polls /api/analyze/<job_id>
    # to know which agent is working (1, 2, 3), then gets the result or the error.
    # Short separate requests are never held back by antivirus/proxy buffering.
    # If the browser goes away, the analysis still finishes (test results are still saved).
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        now = time.time()
        for old_id in [j for j, job in _jobs.items() if now - job["created"] > JOB_TTL_SECONDS]:
            del _jobs[old_id]
        _jobs[job_id] = {"stage": 0, "done": False, "result": None, "error": None, "created": now}

    def set_stage(stage):
        with _jobs_lock:
            _jobs[job_id]["stage"] = stage
        print(f"[live analysis {job_id[:6]}] Agent {stage} started")

    def worker():
        result, error = None, None
        try:
            result = run_analysis(set_stage)
        except AnalysisRejected as e:
            error = str(e)
        except Exception as e:
            error = str(e)[:300]
        with _jobs_lock:
            _jobs[job_id].update({"done": True, "result": result, "error": error})
        print(f"[live analysis {job_id[:6]}] " + ("finished" if error is None else f"failed: {error[:120]}"))

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"job_id": job_id}), 202


@app.route("/api/analyze/<job_id>")
def api_analyze_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "This analysis is unknown or has expired. Run it again."}), 404
        if job["done"]:
            del _jobs[job_id]  # the result is delivered once
        payload = {"stage": job["stage"], "done": job["done"]}
        if job["done"]:
            if job["error"] is not None:
                payload["error"] = job["error"]
            else:
                payload["result"] = job["result"]
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DriverLens Platform dashboard")
    parser.add_argument("--mock", action="store_true", help="use the fake model for live analysis")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    if args.mock:
        LLM_MODE = "mock"
    print("Loading the dataset size...")
    get_pool()
    print(f"Live analysis uses: {analyzer_label()}")
    print(f"Open http://127.0.0.1:{args.port} in your browser (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=args.port, debug=False)