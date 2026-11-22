import hashlib
import random
import re
from typing import Dict, Any

from .base_llm import BaseLLM


class MockLLM(BaseLLM):
    """
    FAKE language model used for `python main.py --dry-run`.

    It answers every prompt with randomly generated text in the exact format the agents
    expect. It lets you check that the whole pipeline is wired correctly without an API key.
    The results are meaningless: never use them for analysis.
    """

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config or {})

    def generate(self, prompt: str, **kwargs) -> str:
        rnd = random.Random(int(hashlib.md5(prompt.encode("utf-8")).hexdigest(), 16))

        if "Generate Mental State Hypothesis Task" in prompt:
            focus = self._find(prompt, r"Target mental state type:\s*(\w+)") or "Emotion"
            options = [c.strip() for c in
                       (self._find(prompt, r"from this list:\s*(.+)") or "no_concern").split(",")]
            concern = rnd.choice([c for c in options if c != "no_concern"] or options)
            return (f"Type: {focus}\n"
                    f"Description: [MOCK] The commenter seems worried about something related to {concern}.\n"
                    f"Latent_Concern: {concern}\n"
                    f"Surface_Sentiment: {rnd.choice(['positive', 'negative', 'neutral', 'mixed'])}\n"
                    f"Evidence: [MOCK] fake evidence")

        if "Domain Constraint Refinement Task" in prompt:
            concern = self._find(prompt, r"Hidden concern label:\s*(\w+)") or "unclear"
            return (f"Revised_Hypothesis: [MOCK] Refined hypothesis about {concern}.\n"
                    f"Latent_Concern: {concern}\n"
                    f"Compliant: yes\n"
                    f"Modification_Log: none")

        if "Estimate Contextual Plausibility" in prompt:
            return f"{rnd.uniform(0.3, 0.9):.2f}"

        if "Estimate Prior Plausibility" in prompt:
            return f"{rnd.uniform(0.1, 0.5):.2f}"

        if "Response Validation Task" in prompt:
            return (f"Empathy: {rnd.uniform(0.8, 0.95):.2f}\n"
                    f"Coherence: {rnd.uniform(0.75, 0.95):.2f}\n"
                    f"Compliance: yes\n"
                    f"Critique: [MOCK] fine")

        if "Response Synthesis Task" in prompt or "Response Optimization Task" in prompt:
            actions = (self._find(prompt, r"Available actions:\s*(.+)") or "NO_ACTION").split(",")
            return (f"Action: {rnd.choice([a.strip() for a in actions])}\n"
                    f"Churn_Risk: {rnd.choice(['low', 'medium', 'high'])}\n"
                    f"Message: [MOCK] This is a fake message, not a real analysis.")

        return "[MOCK] unrecognized prompt"

    @staticmethod
    def _find(text: str, pattern: str):
        match = re.search(pattern, text)
        return match.group(1).strip() if match else None