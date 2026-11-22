from typing import Dict, List, Any, Optional
from .base_agent import BaseAgent
from prompts.prompt_templates import TOM_AGENT_PROMPTS

# Latent concerns the agent can detect behind a comment.
# Can be overridden with config["latent_concerns"].
LATENT_CONCERNS = [
    "range_anxiety",            # fear of running out of battery
    "charging_anxiety",         # charging speed, station scarcity or reliability
    "battery_longevity_fear",   # degradation, replacement cost
    "price_value_concern",      # price, leasing, resale value
    "brand_trust_issue",        # quality, reliability, trust in Renault
    "after_sales_concern",      # dealership, warranty, repairs
    "comfort_design_concern",   # space, comfort, design, features
    "no_concern",               # genuinely satisfied / neutral
]

SENTIMENTS = ["positive", "negative", "neutral", "mixed"]


class ToMAgent(BaseAgent):
    """
    Theory-of-Mind (ToM) Agent: infers what the commenter really feels and fears
    behind the words of a YouTube comment.
    First stage of the ARAT pipeline.
    """

    def __init__(self, config: Dict[str, Any], llm_interface: Any, social_memory_interface: Any):
        """
        Args:
            config: Configuration for the ToM Agent.
            llm_interface: Interface to the language model.
            social_memory_interface: Interface to the memory (profile of the commenter).
        """
        super().__init__(config, llm_interface)
        self.social_memory = social_memory_interface
        self.hypothesis_count_k = config.get("hypothesis_count_k", 5)
        self.latent_concerns = config.get("latent_concerns", LATENT_CONCERNS)
        self.tom_prompts = TOM_AGENT_PROMPTS

    def process(self, user_input: str, conversation_context: List[Dict[str, str]],
                user_id: str = "default_user") -> List[Dict[str, Any]]:
        """
        Generate candidate hypotheses about the commenter's hidden mental state.

        Args:
            user_input: The YouTube comment text.
            conversation_context: Video context (see BaseAgent.build_comment_context).
            user_id: Identifier of the commenter (used to read the memory).

        Returns:
            A list of hypotheses (dicts).
        """
        hypotheses: List[Dict[str, Any]] = []
        formatted_context = self._format_conversation_context(conversation_context)
        social_memory_summary = str(self.social_memory.get_summary(user_id=user_id))
        concern_options = ", ".join(self.latent_concerns)

        for i in range(self.hypothesis_count_k):
            current_focus_type = self._get_next_hypothesis_type_focus(i)
            prompt = self._format_prompt(
                self.tom_prompts["mental_state_hypothesis_generation"],
                u_t=user_input,
                C_t=formatted_context,
                M_t=social_memory_summary,
                T_focus=current_focus_type,
                H_prev=self._summarize_previous(hypotheses),
                concern_options=concern_options,
            )
            raw = self.llm.generate(prompt)
            parsed = self._parse_hypothesis_generation(raw, i, expected_type=current_focus_type)
            if parsed:
                hypotheses.append(parsed)

        return hypotheses

    def _get_next_hypothesis_type_focus(self, index: int) -> str:
        """Cycle through mental-state types to keep the hypotheses diverse."""
        types = ["Belief", "Desire", "Intention", "Emotion", "Thought"]
        return types[index % len(types)]

    def _summarize_previous(self, hypotheses: List[Dict[str, Any]]) -> str:
        """Short list of hypotheses already generated, so the LLM proposes a different one."""
        if not hypotheses:
            return "None yet."
        return "\n".join(
            f"- [{h['type']} / {h['latent_concern']}] {h['explanation']}" for h in hypotheses
        )

    def _normalize_label(self, value: str) -> str:
        return value.strip().lower().replace(" ", "_").replace("-", "_")

    def _parse_hypothesis_generation(self, llm_response: str, hypothesis_index: int,
                                     expected_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Expected LLM output:
            Type: <Belief|Desire|Intention|Emotion|Thought>
            Description: <one sentence>
            Latent_Concern: <one label from the list>
            Surface_Sentiment: <positive|negative|neutral|mixed>
            Evidence: <words or signals in the comment that support this>
        """
        try:
            fields = self._parse_key_value_lines(llm_response)

            explanation = fields.get("description") or llm_response.strip()
            # Keep one hypothesis per requested focus type in the configured order.
            hyp_type = expected_type or fields.get("type") or "Unknown"

            concern = self._normalize_label(fields.get("latent_concern", ""))
            if concern not in self.latent_concerns:
                concern = "unclear"

            sentiment = fields.get("surface_sentiment", "").strip().lower()
            if sentiment not in SENTIMENTS:
                sentiment = "neutral"

            return {
                "id": f"hyp_{hypothesis_index + 1}",
                "type": hyp_type,
                "explanation": explanation,
                "latent_concern": concern,
                "surface_sentiment": sentiment,
                "evidence": fields.get("evidence", "N/A"),
            }
        except Exception as e:
            print(f"[ToMAgent] Error parsing hypothesis: {e}\nResponse: {llm_response}")
            return None
