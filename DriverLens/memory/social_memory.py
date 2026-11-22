import datetime
import hashlib
import json
import logging
import os
import tempfile
from collections import Counter
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

GLOBAL_BUCKET = "__global_social_memory__"
MEMORY_SCHEMA_VERSION = 2


class SocialMemory:
    """Persistent aggregate memory built only from successful training comments."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.salt = self.config.get("salt", "")
        self.max_excerpt_chars = self.config.get("max_excerpt_chars", 200)
        self.user_memory: Dict[str, Dict[str, Any]] = {
            GLOBAL_BUCKET: {"interaction_history": []}
        }

    def make_user_id(self, author: Optional[str], fallback: str = "anonymous") -> str:
        """Kept for compatibility with callers; aggregate memory does not store author IDs."""
        if author is None or not str(author).strip():
            return fallback
        raw = (self.salt + str(author).strip().lower()).encode("utf-8")
        return f"user_{hashlib.sha256(raw).hexdigest()[:12]}"

    def update_memory_from_result(self, user_id: str, user_utterance: str,
                                  selected_hypothesis: Dict[str, Any],
                                  response_result: Dict[str, Any],
                                  car_model: str = "") -> None:
        """Add one successfully analyzed TRAIN comment to the shared memory."""
        excerpt = (user_utterance or "").strip()
        if self.max_excerpt_chars and len(excerpt) > self.max_excerpt_chars:
            excerpt = excerpt[: self.max_excerpt_chars].rstrip() + "..."

        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "car_model": car_model or "unknown",
            "comment_excerpt": excerpt,
            "surface_sentiment": selected_hypothesis.get("surface_sentiment", "neutral"),
            "latent_concern": selected_hypothesis.get("latent_concern", "unclear"),
            "hypothesis_type": selected_hypothesis.get("type", "Unknown"),
            "churn_risk": response_result.get("churn_risk", "medium"),
            "action": response_result.get("action", "NO_ACTION"),
        }
        self.user_memory.setdefault(GLOBAL_BUCKET, {"interaction_history": []})
        self.user_memory[GLOBAL_BUCKET]["interaction_history"].append(entry)
        logger.info("[SocialMemory] Added training comment to global memory (%s).", entry["car_model"])

    def _entries(self) -> List[Dict[str, Any]]:
        return self.user_memory.get(GLOBAL_BUCKET, {}).get("interaction_history", [])

    def get_interaction_history(self, user_id: str = "global", limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent global training records; user_id is accepted for compatibility."""
        return list(reversed(self._entries()))[:limit]

    @staticmethod
    def _top(counter: Counter, limit: int = 5) -> str:
        items = [(key, count) for key, count in counter.most_common(limit) if key]
        return ", ".join(f"{key} ({count})" for key, count in items) or "none recorded"

    def get_summary(self, user_id: str = "global", max_interactions: int = 3) -> str:
        """Build a compact, model-aware summary from the global training memory."""
        entries = self._entries()
        if not entries:
            return "Global training memory is empty. No population-level evidence is available."

        lines = [
            f"GLOBAL TRAINING MEMORY: {len(entries)} successfully analyzed comment(s).",
            "These are aggregate patterns from the training split; do not assume they describe every customer.",
        ]
        by_model: Dict[str, List[Dict[str, Any]]] = {}
        for entry in entries:
            by_model.setdefault(entry.get("car_model", "unknown"), []).append(entry)

        for model in sorted(by_model):
            model_entries = by_model[model]
            sentiments = Counter(e.get("surface_sentiment", "unknown") for e in model_entries)
            concerns = Counter(e.get("latent_concern", "unclear") for e in model_entries
                               if e.get("latent_concern") not in ("no_concern", "unclear", ""))
            risks = Counter(e.get("churn_risk", "unknown") for e in model_entries)
            lines.append(
                f"{model} (n={len(model_entries)}): sentiment {self._top(sentiments)}; "
                f"recurring concerns {self._top(concerns)}; churn risk {self._top(risks, 3)}."
            )
        return "\n".join(lines)

    def get_global_stats(self) -> Dict[str, Any]:
        entries = self._entries()
        concerns_by_model: Dict[str, Counter] = {}
        sentiments_by_model: Dict[str, Counter] = {}
        for entry in entries:
            model = entry.get("car_model", "unknown")
            concerns_by_model.setdefault(model, Counter())[entry.get("latent_concern", "unclear")] += 1
            sentiments_by_model.setdefault(model, Counter())[entry.get("surface_sentiment", "unknown")] += 1

        return {
            "total_comments": len(entries),
            "by_surface_sentiment": dict(Counter(e.get("surface_sentiment", "unknown") for e in entries)),
            "by_latent_concern": dict(Counter(e.get("latent_concern", "unclear") for e in entries)),
            "by_churn_risk": dict(Counter(e.get("churn_risk", "unknown") for e in entries)),
            "by_action": dict(Counter(e.get("action", "NO_ACTION") for e in entries)),
            "concerns_by_car_model": {m: dict(c) for m, c in concerns_by_model.items()},
            "sentiments_by_car_model": {m: dict(c) for m, c in sentiments_by_model.items()},
        }

    def get_all_data_for_user(self, user_id: str = "global") -> Optional[Dict[str, Any]]:
        """Return the global memory bucket; user_id is accepted for compatibility."""
        return self.user_memory.get(GLOBAL_BUCKET)

    def save(self, path: str) -> None:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        payload = {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "memory_type": "global_training_memory",
            "interaction_history": self._entries(),
        }
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=folder or ".", delete=False,
                prefix=".global_memory_", suffix=".tmp"
            ) as f:
                temp_path = f.name
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("schema_version") != MEMORY_SCHEMA_VERSION:
            raise ValueError(
                "This memory file uses an older format. Rebuild it with the training phase "
                "or choose a new global-memory file."
            )
        self.user_memory = {
            GLOBAL_BUCKET: {"interaction_history": payload.get("interaction_history", [])}
        }
        return True

    def clear_user_memory(self, user_id: str = "global") -> None:
        """Clear the aggregate bucket (does not delete its saved file)."""
        self.user_memory[GLOBAL_BUCKET] = {"interaction_history": []}
