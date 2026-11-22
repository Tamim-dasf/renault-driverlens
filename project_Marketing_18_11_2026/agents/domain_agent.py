import math
from typing import Dict, List, Any
from .base_agent import BaseAgent
from prompts.prompt_templates import DOMAIN_AGENT_PROMPTS

# Default rules for the French market. Editable via config["domain_rules"].
# NOTE: these are working guidelines for the project, not legal advice.
DEFAULT_DOMAIN_RULES: Dict[str, List[str]] = {
    "cultural": [
        "French consumers often express dissatisfaction through irony, understatement or sarcasm; do not read comments only literally.",
        "Comments may mix French and English or use automotive slang (autonomie, borne, recharge rapide, wallbox).",
        "Distinguish a real personal experience from a hypothetical worry or something heard from others.",
    ],
    "ethical": [
        "Do not infer sensitive personal data about the commenter (health, religion, politics, etc.).",
        "Do not exploit emotional vulnerability to push a sale; the goal is to inform and reassure, not to pressure.",
    ],
    "regulatory": [
        "Any commercial claim (range, charging time, price) must be accurate and verifiable; no misleading promises (consumer law).",
        "Respect data minimization (GDPR/RGPD): do not try to identify the author of the comment.",
    ],
    "role": [
        "Hypotheses must be useful to a Renault retention, marketing or customer-experience team.",
    ],
}


class DomainAgent(BaseAgent):
    """
    Domain Agent (Moral & Cultural): checks each hypothesis against French market norms,
    ethics and regulation, then selects the most plausible and informative one.
    Second stage of the ARAT pipeline.
    """

    def __init__(self, config: Dict[str, Any], llm_interface: Any, social_memory_interface: Any):
        """
        Args:
            config: Configuration for the Domain Agent.
            llm_interface: Interface to the language model.
            social_memory_interface: Interface to the memory (context for P_cond).
        """
        super().__init__(config, llm_interface)
        self.social_memory = social_memory_interface
        self.lambda_weight = config.get("lambda_weight", 0.6)
        self.domain_rules = config.get("domain_rules", DEFAULT_DOMAIN_RULES)
        self.domain_prompts = DOMAIN_AGENT_PROMPTS
        self.epsilon = 1e-9  # keeps log() stable
        self._prior_cache: Dict[Any, float] = {}

    def process(self, hypotheses: List[Dict[str, Any]], user_input: str,
                conversation_context: List[Dict[str, str]],
                user_id: str = "default_user") -> Dict[str, Any]:
        """
        Refine the hypotheses with domain rules and return the best one.

        Args:
            hypotheses: Candidate hypotheses from the ToMAgent.
            user_input: The YouTube comment text.
            conversation_context: Video context.
            user_id: Identifier of the commenter (used to read the memory).
        """
        refined = []
        for h in hypotheses:
            refined_h = self._refine_hypothesis_with_constraints(h)
            refined_h["original_hypothesis_id"] = h.get("id")
            refined.append(refined_h)

        selected = self._select_hypothesis(refined, user_input, conversation_context, user_id)
        # Keep a compact audit trail for the interface's optional detailed view.
        # Only structured outputs and scores are exposed; prompts and private reasoning are not.
        selected["candidate_hypotheses"] = [dict(h) for h in refined]
        return selected

    # ------------------------------------------------------------------
    # Step 1: domain constraint refinement
    # ------------------------------------------------------------------
    def _format_rules(self) -> str:
        lines = []
        for category, rules in self.domain_rules.items():
            lines.append(f"[{category.upper()}]")
            lines.extend(f"- {rule}" for rule in rules)
        return "\n".join(lines)

    def _refine_hypothesis_with_constraints(self, hypothesis: Dict[str, Any]) -> Dict[str, Any]:
        """Check one hypothesis against all the rules and revise it if needed (one LLM call)."""
        prompt = self._format_prompt(
            self.domain_prompts["constraint_refinement"],
            h_i_id=hypothesis.get("id", "N/A"),
            h_i_type=hypothesis.get("type", "Unknown"),
            h_i_explanation=hypothesis.get("explanation", ""),
            h_i_latent_concern=hypothesis.get("latent_concern", "unclear"),
            constraint_specifications=self._format_rules(),
        )
        response = self.llm.generate(prompt)
        return self._parse_refinement_response(response, hypothesis)

    def _parse_refinement_response(self, llm_response: str, hypothesis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected LLM output:
            Revised_Hypothesis: <sentence>
            Latent_Concern: <label>
            Compliant: <yes|no>
            Modification_Log: <what was changed and why, or 'none'>
        """
        fields = self._parse_key_value_lines(llm_response)
        refined = dict(hypothesis)

        refined["original_explanation"] = hypothesis.get("explanation", "")
        refined["explanation"] = fields.get("revised_hypothesis") or hypothesis.get("explanation", "")

        concern = fields.get("latent_concern", "").strip().lower().replace(" ", "_").replace("-", "_")
        if concern:
            refined["latent_concern"] = concern

        refined["compliant"] = fields.get("compliant", "yes").strip().lower().startswith("y")
        refined["modification_log"] = fields.get("modification_log", "none")
        return refined

    # ------------------------------------------------------------------
    # Step 2: hypothesis selection (contextual plausibility + information gain)
    # ------------------------------------------------------------------
    def _select_hypothesis(self, refined_hypotheses: List[Dict[str, Any]], user_input: str,
                           conversation_context: List[Dict[str, str]],
                           user_id: str) -> Dict[str, Any]:
        """
        score_i = lambda * P_cond + (1 - lambda) * IG_i
        IG_i    = log(P_cond) - log(P_prior)
        Non-compliant hypotheses are excluded unless none is compliant.
        """
        if not refined_hypotheses:
            return {"explanation": "No suitable hypothesis found.", "type": "Error",
                    "latent_concern": "unclear", "surface_sentiment": "neutral", "score": -1}

        candidates = [h for h in refined_hypotheses if h.get("compliant", True)] or refined_hypotheses

        formatted_context = self._format_conversation_context(conversation_context)
        memory_summary = str(self.social_memory.get_summary(user_id=user_id))

        best, max_score = None, -float("inf")
        for h in candidates:
            p_cond = self._get_conditional_probability(h, user_input, formatted_context, memory_summary)
            p_prior = self._get_prior_probability(h)
            ig = math.log(p_cond + self.epsilon) - math.log(p_prior + self.epsilon)
            score = self.lambda_weight * p_cond + (1 - self.lambda_weight) * ig

            h["p_cond"], h["p_prior"], h["ig"], h["score"] = p_cond, p_prior, ig, score
            if score > max_score:
                max_score, best = score, h

        return best if best else candidates[0]

    def _get_conditional_probability(self, hypothesis: Dict[str, Any], user_input: str,
                                     formatted_context: str, memory_summary: str) -> float:
        """P(h | comment, video context, memory): how plausible is this hypothesis here?"""
        prompt = self._format_prompt(
            self.domain_prompts["conditional_probability"],
            h_tilde_i_explanation=hypothesis.get("explanation", ""),
            h_tilde_i_type=hypothesis.get("type", "Unknown"),
            h_tilde_i_latent_concern=hypothesis.get("latent_concern", "unclear"),
            u_t=user_input,
            C_t=formatted_context,
            M_t=memory_summary,
        )
        return self._probability(self.llm.generate(prompt))

    def _get_prior_probability(self, hypothesis: Dict[str, Any]) -> float:
        """
        P(h): how common is this kind of concern in EV comments in general,
        regardless of this specific comment. Cached by (type, latent_concern).
        """
        key = (hypothesis.get("type"), hypothesis.get("latent_concern"))
        if key in self._prior_cache:
            return self._prior_cache[key]

        prompt = self._format_prompt(
            self.domain_prompts["prior_probability"],
            h_tilde_i_type=hypothesis.get("type", "Unknown"),
            h_tilde_i_latent_concern=hypothesis.get("latent_concern", "unclear"),
        )
        p = self._probability(self.llm.generate(prompt))
        self._prior_cache[key] = p
        return p

    def _probability(self, llm_response: str) -> float:
        """Parse a probability and keep it away from 0 and 1 so the log stays stable."""
        return max(0.01, min(0.99, self._to_score(llm_response, default=0.5)))
