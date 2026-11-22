import re
from typing import Dict, Any, List, Optional


class BaseAgent:
    """
    Base class for all agents in the Renault ARAT Platform
    (adapted from the MetaMind framework).

    The "conversation" is now a single YouTube comment plus its video context
    (car model, video title, channel...).
    """

    def __init__(self, config: Dict[str, Any], llm_interface: Any):
        """
        Args:
            config: Configuration for the agent.
            llm_interface: Interface to the language model (must expose .generate(prompt) -> str).
        """
        self.config = config
        self.llm = llm_interface

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------
    def _format_prompt(self, template: str, **kwargs) -> str:
        """Fill a prompt template. Literal braces in templates must be written {{ }}."""
        return template.format(**kwargs)

    def _format_conversation_context(self, conversation_context: List[Dict[str, str]]) -> str:
        """
        Format the context of a comment (car model, video title, parent comment...)
        as plain text for the prompts.
        """
        if not conversation_context:
            return "No video context available."

        lines = []
        for turn in conversation_context:
            speaker = turn.get("speaker", "Unknown")
            utterance = turn.get("utterance", "")
            lines.append(f"{speaker}: {utterance}")
        return "\n".join(lines)

    @staticmethod
    def build_comment_context(video_title: str = "", channel: str = "", car_model: str = "",
                              parent_comment: Optional[str] = None,
                              likes: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Build the context list from one row of the CSV.
        Only non-empty fields are included.
        """
        context = []
        if car_model:
            context.append({"speaker": "Car model", "utterance": car_model})
        if video_title:
            context.append({"speaker": "Video title", "utterance": video_title})
        if channel:
            context.append({"speaker": "YouTube channel", "utterance": channel})
        if parent_comment:
            context.append({"speaker": "Parent comment", "utterance": parent_comment})
        if likes is not None:
            context.append({"speaker": "Likes on the comment", "utterance": str(likes)})
        return context

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_key_value_lines(text: str) -> Dict[str, str]:
        """
        Parse lines like 'Type: Emotion' into {'type': 'Emotion'}.
        Keys are lowercased, spaces become underscores, markdown symbols are ignored.
        The first occurrence of a key wins.
        """
        parsed: Dict[str, str] = {}
        for line in text.strip().split("\n"):
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip(" -*_#•\t").lower().replace(" ", "_")
            value = value.strip(" *\t")
            if key and key not in parsed:
                parsed[key] = value
        return parsed

    @staticmethod
    def _to_score(text: Any, default: float = 0.5) -> float:
        """
        Extract a number from LLM text and return it as a score in [0, 1].
        Handles '0.8', '0,8', '8/10' (-> 0.8) and '80' (-> 0.8).
        """
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(text))
        if not match:
            return default
        value = float(match.group().replace(",", "."))
        if value > 1:
            value = value / 10 if value <= 10 else value / 100
        return max(0.0, min(1.0, value))

    def process(self, *args, **kwargs) -> Any:
        """Main processing method. Each agent must implement its own."""
        raise NotImplementedError("Each agent must implement its own process method.")