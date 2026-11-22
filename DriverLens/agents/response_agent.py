import re
from typing import Dict, List, Any, Tuple
from .base_agent import BaseAgent
from prompts.prompt_templates import RESPONSE_AGENT_PROMPTS

# The three actions of the ARAT platform (+ NO_ACTION for satisfied customers).
ALLOWED_ACTIONS = [
    "AUTOMATED_RETENTION",   # Action 01: automated system trigger
    "DEALERSHIP_GUIDANCE",   # Action 02: customized script for the dealership
    "DIRECT_OUTREACH",       # Action 03: empathy notification & targeted offer
    "NO_ACTION",
]

RISK_LEVELS = ["low", "medium", "high"]


class ResponseAgent(BaseAgent):
    """
    Response Agent: turns the selected hypothesis into a concrete retention action,
    validates it, and revises it until its utility is high enough.
    Third stage of the ARAT pipeline.
    """

    def __init__(self, config: Dict[str, Any], llm_interface: Any):
        """
        Args:
            config: Configuration for the Response Agent.
            llm_interface: Interface to the language model.
        """
        super().__init__(config, llm_interface)
        self.beta = config.get("beta", 0.8)
        self.utility_threshold = config.get("utility_threshold", 0.8)
        self.max_revisions = config.get("max_revisions", 2)
        self.allowed_actions = config.get("allowed_actions", ALLOWED_ACTIONS)

    def process(self, selected_hypothesis: Dict[str, Any], user_input: str,
                conversation_context: List[Dict[str, str]],
                social_memory: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate, validate and (if needed) optimize the final action.

        Returns:
            {"action", "churn_risk", "message", "validation", "revisions_done"}
        """
        response = self._generate_response(selected_hypothesis, user_input,
                                           conversation_context, social_memory)
        validation = self._validate_response(response, selected_hypothesis, user_input,
                                             conversation_context, social_memory)
        initial_response = dict(response)
        revision_trace = [{"revision": 0, "response": dict(response), "validation": dict(validation)}]

        revisions = 0
        while validation["utility"] < self.utility_threshold and revisions < self.max_revisions:
            print(f"[ResponseAgent] Utility {validation['utility']:.2f} < {self.utility_threshold}. "
                  f"Optimizing (revision {revisions + 1}).")
            response, validation = self._optimize_response(response, validation, selected_hypothesis,
                                                           user_input, conversation_context, social_memory)
            revisions += 1
            revision_trace.append({"revision": revisions, "response": dict(response),
                                   "validation": dict(validation)})

        if validation["utility"] < self.utility_threshold:
            print(f"[ResponseAgent] Max revisions reached. Final utility {validation['utility']:.2f}.")

        return {
            "action": response["action"],
            "churn_risk": response["churn_risk"],
            "message": response["message"],
            "validation": validation,
            "revisions_done": revisions,
            "initial_response": initial_response,
            "revision_trace": revision_trace,
        }

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def _generate_response(self, hypothesis: Dict[str, Any], user_input: str,
                           conversation_context: List[Dict[str, str]],
                           social_memory: Dict[str, Any]) -> Dict[str, str]:
        prompt = self._format_prompt(
            RESPONSE_AGENT_PROMPTS["response_synthesis"],
            h_tilde_explanation=hypothesis.get("explanation", "N/A"),
            h_tilde_type=hypothesis.get("type", "Unknown"),
            h_tilde_latent_concern=hypothesis.get("latent_concern", "unclear"),
            M_t=str(social_memory),
            C_t=self._format_conversation_context(conversation_context),
            u_t=user_input,
            allowed_actions=", ".join(self.allowed_actions),
        )
        return self._parse_response_generation(self.llm.generate(prompt))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_response(self, response: Dict[str, str], hypothesis: Dict[str, Any],
                           user_input: str, conversation_context: List[Dict[str, str]],
                           social_memory: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._format_prompt(
            RESPONSE_AGENT_PROMPTS["response_validation"],
            o_t=self._response_to_text(response),
            h_tilde_explanation=hypothesis.get("explanation", "N/A"),
            h_tilde_type=hypothesis.get("type", "Unknown"),
            h_tilde_latent_concern=hypothesis.get("latent_concern", "unclear"),
            M_t=str(social_memory),
            C_t=self._format_conversation_context(conversation_context),
            u_t=user_input,
            beta=self.beta,
        )
        return self._parse_validation_results(self.llm.generate(prompt))

    # ------------------------------------------------------------------
    # Optimization
    # ------------------------------------------------------------------
    def _optimize_response(self, original: Dict[str, str], validation: Dict[str, Any],
                           hypothesis: Dict[str, Any], user_input: str,
                           conversation_context: List[Dict[str, str]],
                           social_memory: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, Any]]:
        prompt = self._format_prompt(
            RESPONSE_AGENT_PROMPTS["response_optimization"],
            original_response=self._response_to_text(original),
            critique=validation.get("critique", "No specific critique provided."),
            h_tilde_explanation=hypothesis.get("explanation", "N/A"),
            h_tilde_type=hypothesis.get("type", "Unknown"),
            h_tilde_latent_concern=hypothesis.get("latent_concern", "unclear"),
            u_t=user_input,
            C_t=self._format_conversation_context(conversation_context),
            M_t=str(social_memory),
            allowed_actions=", ".join(self.allowed_actions),
        )
        new_response = self._parse_response_generation(self.llm.generate(prompt))
        new_validation = self._validate_response(new_response, hypothesis, user_input,
                                                 conversation_context, social_memory)
        return new_response, new_validation

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _response_to_text(self, response: Dict[str, str]) -> str:
        return (f"Action: {response['action']}\n"
                f"Churn_Risk: {response['churn_risk']}\n"
                f"Message: {response['message']}")

    def _normalize_action(self, value: str) -> str:
        cleaned = value.strip().upper().replace(" ", "_").replace("-", "_")
        if cleaned in self.allowed_actions:
            return cleaned
        for action in self.allowed_actions:  # tolerate extra words around the label
            if action in cleaned:
                return action
        return "NO_ACTION"

    def _parse_response_generation(self, llm_response: str) -> Dict[str, str]:
        """
        Expected LLM output (Message must be the LAST field, it can span several lines):
            Action: <AUTOMATED_RETENTION|DEALERSHIP_GUIDANCE|DIRECT_OUTREACH|NO_ACTION>
            Churn_Risk: <low|medium|high>
            Message: <text, in the same language as the comment>
        """
        fields = self._parse_key_value_lines(llm_response)

        risk = fields.get("churn_risk", "").strip().lower()
        risk = risk if risk in RISK_LEVELS else "medium"

        match = re.search(r"message\s*:\s*(.*)$", llm_response, flags=re.IGNORECASE | re.DOTALL)
        message = match.group(1).lstrip("* ").strip() if match else llm_response.strip()

        return {
            "action": self._normalize_action(fields.get("action", "")),
            "churn_risk": risk,
            "message": message,
        }

    def _parse_validation_results(self, llm_response: str) -> Dict[str, Any]:
        """
        Expected LLM output:
            Empathy: <0-1>
            Coherence: <0-1>      (is the action the right one for the latent concern?)
            Compliance: <yes|no>  (respects French norms, GDPR, no pressure or false claims)
            Critique: <one or two sentences>

        utility = beta * empathy + (1 - beta) * coherence
        A non-compliant response is capped at 0.5 so it always gets revised.
        """
        results = {"utility": 0.1, "empathy": 0.0, "coherence": 0.0,
                   "compliant": True, "critique": "Parsing failed."}
        try:
            fields = self._parse_key_value_lines(llm_response)

            results["empathy"] = self._to_score(fields.get("empathy", ""), default=0.0)
            results["coherence"] = self._to_score(fields.get("coherence", ""), default=0.0)
            results["compliant"] = fields.get("compliance", "yes").strip().lower().startswith("y")
            results["critique"] = fields.get("critique", "No specific critique provided.")

            if "empathy" in fields and "coherence" in fields:
                utility = self.beta * results["empathy"] + (1 - self.beta) * results["coherence"]
            else:
                utility = self._to_score(fields.get("utility", ""), default=0.1)

            if not results["compliant"]:
                utility = min(utility, 0.5)
            results["utility"] = utility
        except Exception as e:
            print(f"[ResponseAgent] Error parsing validation: {e}\nResponse: {llm_response}")
            results["critique"] = f"Error parsing validation: {e}"
        return results
