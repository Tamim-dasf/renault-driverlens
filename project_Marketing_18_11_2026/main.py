
"""
Renault ARAT Platform: runs the three agents (Theory of Mind -> Domain -> Response)
on YouTube comments about Renault electric cars.

Usage (from the 'real project' folder):
    python main.py --phase train --dry-run   build a demo global memory (no API key)
    python main.py --phase train             process the 60% training split
    python main.py --phase test               test one held-out comment per model
A stopped training run can be resumed; the saved split and completed IDs stay fixed.
"""
import argparse
import glob
import hashlib
import json
import os
import sys
from typing import Any, Callable, Dict, Optional, Tuple

import pandas as pd

import config
from agents import ToMAgent, DomainAgent, ResponseAgent, BaseAgent
from llm_interface import MockLLM
from memory import SocialMemory
from utils import (load_comments, describe_data, sample_comments, build_result_row,
                   remove_user_mentions,
                   append_result, load_done_ids)


def _stratify_model(group: pd.DataFrame, seed: int, train_fraction: float):
    """Split one model's rows deterministically while keeping at least one row per side."""
    if len(group) < 2:
        raise ValueError(
            f"Model '{group.iloc[0]['car_model']}' has fewer than two comments; "
            "a train/test split needs at least one comment in each part."
        )
    model_name = str(group.iloc[0]["car_model"])
    model_seed = int(hashlib.sha1(model_name.encode("utf-8")).hexdigest()[:8], 16)
    shuffled = group.sort_values("comment_id").sample(frac=1, random_state=(seed + model_seed) % (2**32 - 1))
    train_count = max(1, min(len(group) - 1, int(round(len(group) * train_fraction))))
    train_ids = shuffled.iloc[:train_count]["comment_id"].astype(str).tolist()
    test_ids = shuffled.iloc[train_count:]["comment_id"].astype(str).tolist()
    return train_ids, test_ids


def load_or_create_split(data: pd.DataFrame, path: str, seed: int,
                         train_fraction: float, create: bool) -> Dict[str, Any]:
    """Keep a persisted, per-model split stable and assign later additions near the same ratio."""
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1.")

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assignments = manifest.get("assignments", {})
        test_examples = manifest.get("test_examples", {})
    elif create:
        assignments, test_examples = {}, {}
        manifest = {"version": 1, "seed": seed, "train_fraction": train_fraction}
    else:
        raise FileNotFoundError("No saved train/test split. Run the training phase first.")

    known_models = set(manifest.get("models", []))
    for model, group in data.groupby("car_model", sort=True):
        model = str(model)
        current_ids = group["comment_id"].astype(str).tolist()
        new_ids = [comment_id for comment_id in current_ids if comment_id not in assignments]

        if not assignments or model not in known_models:
            train_ids, test_ids = _stratify_model(group, seed, train_fraction)
            assignments.update({comment_id: "train" for comment_id in train_ids})
            assignments.update({comment_id: "test" for comment_id in test_ids})
            if test_ids:
                # Save one fixed, held-out example per model for the four-comment test run.
                test_examples[model] = test_ids[0]
        else:
            # Preserve the existing holdout while placing new comments close to the 60/40 ratio.
            model_ids = [cid for cid in current_ids if cid in assignments]
            train_count = sum(assignments[cid] == "train" for cid in model_ids)
            test_count = sum(assignments[cid] == "test" for cid in model_ids)
            stable_new_order = sorted(
                new_ids, key=lambda cid: hashlib.sha1(f"{seed}|{model}|{cid}".encode("utf-8")).hexdigest()
            )
            for comment_id in stable_new_order:
                if train_count / max(1, train_count + test_count) < train_fraction:
                    assignments[comment_id] = "train"
                    train_count += 1
                else:
                    assignments[comment_id] = "test"
                    test_count += 1

    manifest.update({
        "version": 1,
        "seed": seed,
        "train_fraction": train_fraction,
        "test_fraction": 1 - train_fraction,
        "assignments": assignments,
        "test_examples": test_examples,
        "models": sorted(data["car_model"].astype(str).unique().tolist()),
    })
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def rebuild_memory_from_results(memory: SocialMemory, results_file: str) -> None:
    """Recreate the aggregate memory from saved successful training outputs, without API calls."""
    if not os.path.exists(results_file):
        return
    rows = pd.read_csv(results_file, dtype=str, encoding="utf-8-sig").fillna("")
    if "error" in rows.columns:
        rows = rows[rows["error"] == ""]
    if "comment_id" in rows.columns:
        rows = rows.drop_duplicates("comment_id", keep="last")
    memory.user_memory = {}
    for row in rows.to_dict(orient="records"):
        memory.update_memory_from_result(
            "global",
            row.get("comment", ""),
            {
                "surface_sentiment": row.get("surface_sentiment", "neutral"),
                "latent_concern": row.get("latent_concern", "unclear"),
                "type": row.get("hypothesis_type", "Unknown"),
            },
            {"churn_risk": row.get("churn_risk", "medium"),
             "action": row.get("action", "NO_ACTION")},
            row.get("car_model", "unknown"),
        )


def test_results_for_training_snapshot(base_path: str, train_ids: set) -> str:
    """Give each distinct training-memory snapshot its own held-out test result file."""
    root, extension = os.path.splitext(base_path)
    fingerprint = hashlib.sha1("\n".join(sorted(train_ids)).encode("utf-8")).hexdigest()[:10]
    return f"{root}_after_{len(train_ids)}_train_{fingerprint}{extension}"


def clean_value(value: Any) -> Any:
    """Turn pandas NaN / empty strings into None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def build_llm(dry_run: bool):
    if dry_run:
        print("DRY RUN: using a FAKE model. Results are random and only test the wiring.\n")
        return MockLLM()

    if not config.LLM_CONFIG.get("api_key"):
        sys.exit("No Gemini API key found. Create a '.env' file next to main.py containing:\n"
                 "GEMINI_API_KEY=your_key_here")
    from llm_interface import GeminiLLM  # imported here so --dry-run needs no google library
    print(f"Using Gemini model: {config.LLM_CONFIG['model_name']}\n")
    return GeminiLLM(config.LLM_CONFIG)


def process_comment(item: Dict[str, Any], tom: ToMAgent, domain: DomainAgent,
                    responder: ResponseAgent, memory: SocialMemory,
                    user_id: str,
                    on_stage: Optional[Callable[[int], None]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run one comment through the three stages.

    on_stage (optional) is called with 1, 2 then 3 just before each agent starts,
    so the web interface can show which agent is working.
    """
    notify = on_stage or (lambda stage: None)
    likes = clean_value(item.get("likes"))
    context = BaseAgent.build_comment_context(
        video_title=clean_value(item.get("video_title")) or "",
        car_model=item["car_model"],
        parent_comment=clean_value(item.get("parent_comment")),
        likes=int(likes) if likes is not None else None,
    )
    comment = remove_user_mentions(item["comment"])
    item["comment"] = comment

    notify(1)
    hypotheses = tom.process(comment, context, user_id=user_id)
    notify(2)
    selected = domain.process(hypotheses, comment, context, user_id=user_id)
    if selected.get("type") == "Error":
        raise RuntimeError("The Theory of Mind agent produced no usable hypothesis.")
    selected["initial_hypotheses"] = [dict(h) for h in hypotheses]

    notify(3)
    response = responder.process(selected, comment, context, memory.get_summary(user_id))
    return selected, response


def print_summary(memory: SocialMemory, results_file: str) -> None:
    stats = memory.get_global_stats()
    print(f"\nComments in memory: {stats['total_comments']}")
    for title, key in [("Hidden concerns", "by_latent_concern"),
                       ("Churn risk", "by_churn_risk"),
                       ("Actions", "by_action")]:
        counts = sorted(stats[key].items(), key=lambda kv: -kv[1])
        print(f"{title}: " + ", ".join(f"{k} ({v})" for k, v in counts))
    print(f"\nResults saved in: {results_file}")


def run(args: argparse.Namespace) -> None:
    run_cfg = config.RUN_CONFIG
    training = args.phase == "train"
    if args.dry_run:
        train_results_file = config.DRY_RUN_RESULTS_FILE
        results_file = train_results_file if training else config.DRY_RUN_TEST_RESULTS_FILE
        memory_file = config.DRY_RUN_MEMORY_FILE
        manifest_file = config.SPLIT_FILE
    else:
        train_results_file = config.RESULTS_FILE
        results_file = train_results_file if training else config.TEST_RESULTS_FILE
        memory_file = config.MEMORY_FILE
        manifest_file = config.SPLIT_FILE

    if args.reset:
        if not args.dry_run or not training:
            raise ValueError("--reset is available only with --phase train --dry-run.")
        for path in (config.DRY_RUN_RESULTS_FILE, config.DRY_RUN_TEST_RESULTS_FILE,
                     config.DRY_RUN_MEMORY_FILE, *glob.glob(
                         os.path.join(config.RESULTS_DIR, "dry_run_test_results_after_*_train_*.csv")
                     )):
            if os.path.exists(path):
                os.remove(path)

    # 1. Load all model files and create/load the stable stratified manifest.
    data = load_comments(config.DATA_DIR, file_car_models=run_cfg["file_car_models"])
    describe_data(data)
    manifest = load_or_create_split(
        data, manifest_file, run_cfg["random_seed"], run_cfg["train_fraction"], create=training
    )
    assignments = manifest["assignments"]
    data_ids = data["comment_id"].astype(str)
    if training:
        selected_ids = {cid for cid in data_ids if assignments.get(cid) == "train"}
        phase_data = data[data_ids.isin(selected_ids)].copy()
    else:
        selected_ids = set(manifest.get("test_examples", {}).values())
        missing_examples = selected_ids - set(data_ids)
        if missing_examples:
            raise ValueError("A saved test comment is missing from the source data; rebuild the split manifest.")
        phase_data = data[data_ids.isin(selected_ids)].copy()
        expected_models = set(manifest.get("test_examples", {}))
        actual_models = set(phase_data["car_model"].astype(str))
        if expected_models != actual_models:
            raise ValueError("The saved test split does not contain one example for every model.")

    train_ids = {cid for cid in data_ids if assignments.get(cid) == "train"}
    train_done = load_done_ids(train_results_file)
    memory = SocialMemory(config.MEMORY_CONFIG)
    memory_loaded = memory.load(memory_file)

    if training:
        # Rebuild from existing successful result rows if memory is missing or out of sync.
        if train_done - train_ids:
            raise ValueError("Training results contain IDs outside the saved training split; check the split manifest.")
        if memory.get_global_stats()["total_comments"] != len(train_done):
            rebuild_memory_from_results(memory, config.DRY_RUN_RESULTS_FILE if args.dry_run else config.RESULTS_FILE)
            memory.save(memory_file)
            memory_loaded = True
        remaining = phase_data[~phase_data["comment_id"].astype(str).isin(train_done)]
        batch_size = args.n if args.n is not None else run_cfg["sample_size"]
        todo = sample_comments(remaining, batch_size, seed=run_cfg["random_seed"] + len(train_done))
        print(f"TRAIN: {len(train_ids)} comments in the 60% split; "
              f"{len(train_done & train_ids)} complete; {len(todo)} in this batch.\n")
    else:
        if not memory_loaded:
            raise ValueError("Global training memory is missing. Run the training phase first.")
        if not train_done:
            raise ValueError("No successful training comments yet. Run the training phase first.")
        if train_done - train_ids:
            raise ValueError("Training results contain IDs outside the saved training split; check the split manifest.")
        if memory.get_global_stats()["total_comments"] != len(train_done):
            raise ValueError("Saved global memory does not match successful training results. "
                             "Run the training phase to rebuild it before testing.")
        results_file = test_results_for_training_snapshot(results_file, train_done)
        test_done = load_done_ids(results_file)
        todo = phase_data[~phase_data["comment_id"].astype(str).isin(test_done)]
        print(f"TEST: {len(phase_data)} held-out comments (one per model) using the "
              f"{len(train_done)} training comments accumulated so far; "
              f"{len(todo)} to process. The saved memory will not be changed.\n")

    # 2. Build agents with the same pipeline for both phases.
    llm = build_llm(args.dry_run)
    tom = ToMAgent(config.TOM_CONFIG, llm, memory)
    domain = DomainAgent(config.DOMAIN_CONFIG, llm, memory)
    responder = ResponseAgent(config.RESPONSE_CONFIG, llm)

    # 3. Process one row at a time. Only training success updates the global memory.
    errors_in_a_row = 0
    for i, (_, row) in enumerate(todo.iterrows(), start=1):
        item = row.to_dict()
        try:
            selected, response = process_comment(item, tom, domain, responder, memory,
                                                 user_id=f"row_{item['comment_id']}")
        except Exception as e:
            errors_in_a_row += 1
            append_result(results_file, build_result_row(item, error=str(e)[:300]))
            print(f"[{i}/{len(todo)}] ERROR on {item['comment_id']}: {str(e)[:150]}")
            if errors_in_a_row >= run_cfg["max_consecutive_errors"]:
                print("\nStopped after consecutive errors. Correct the key/quota issue and rerun; "
                      "successful comments will be skipped.")
                break
            continue

        errors_in_a_row = 0
        append_result(results_file, build_result_row(item, selected, response))
        if training:
            memory.update_memory_from_result("global", item["comment"], selected, response, item["car_model"])
            memory.save(memory_file)
        print(f"[{i}/{len(todo)}] {item['car_model']} | {selected.get('latent_concern')} | "
              f"risk {response['churn_risk']} | {response['action']}")

    if training:
        print_summary(memory, results_file)
    else:
        print(f"\nTest results saved in: {results_file}")
        print("Global training memory was left unchanged.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Renault ARAT Platform")
    parser.add_argument("--phase", choices=("train", "test"), default="train",
                        help="train the global memory, or test one held-out comment per model")
    parser.add_argument("--dry-run", action="store_true",
                        help="use a fake model: test the wiring without an API key")
    parser.add_argument("--n", type=int, default=None,
                        help="training comments to process in this run (default: sample_size in config.py)")
    parser.add_argument("--reset", action="store_true",
                        help="clear demo train/test outputs and demo memory before a dry-run training phase")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
