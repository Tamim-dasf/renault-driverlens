import time
from typing import Dict, Any

from google import genai
from google.genai import types, errors

from .base_llm import BaseLLM

# HTTP codes worth retrying: rate limit (free tier!) and temporary server problems.
RETRYABLE_CODES = (429, 500, 503, 504)


class GeminiLLM(BaseLLM):
    """
    LLM interface for Google Gemini (replaces OpenAILLM from MetaMind).
    Same contract: generate(prompt) -> str.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: Configuration dictionary containing:
                - api_key: Gemini API key (from Google AI Studio).
                - model_name: Gemini model ID. Check the current free-tier model in AI Studio.
                - default_max_tokens: max output tokens (thinking tokens count too, keep it generous).
                - default_temperature: default temperature.
                - thinking_level: "low", "medium" or "high" (None to use the model default).
                - max_retries: attempts per call before giving up.
                - min_interval_seconds: pause between calls, to stay under free-tier rate limits.
                - timeout_seconds: a call that takes longer than this is cancelled and retried.
        """
        super().__init__(config)
        api_key = self.config.get("api_key")
        if not api_key:
            raise ValueError("Gemini API key not found in config (check your .env file).")

        self.timeout_seconds = self.config.get("timeout_seconds", 60)
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)),  # milliseconds
        )
        self.model_name = self.config.get("model_name", "gemini-3.8-flash")
        self.default_max_tokens = self.config.get("default_max_tokens", 2048)
        self.default_temperature = self.config.get("default_temperature", 0.7)
        self.thinking_level = self.config.get("thinking_level", "low")
        self.max_retries = self.config.get("max_retries", 4)
        self.min_interval = self.config.get("min_interval_seconds", 0)
        self._last_call = 0.0

    def _throttle(self) -> None:
        """Wait if needed so that two calls are at least min_interval seconds apart."""
        if self.min_interval > 0:
            wait = self.min_interval - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
        self._last_call = time.time()

    def generate(self, prompt: str, **kwargs) -> str:
        """
        Generate text with the configured Gemini model.

        Args:
            prompt: The input prompt string.
            **kwargs: Optional overrides: 'max_tokens', 'temperature'.

        Returns:
            The generated text.

        Raises:
            RuntimeError: if every attempt fails. We raise instead of returning an error
            string (as the OpenAI version did), so an error can never be parsed as a
            real hypothesis or action.
        """
        settings = {
            "temperature": kwargs.get("temperature", self.default_temperature),
            "max_output_tokens": kwargs.get("max_tokens", self.default_max_tokens),
        }
        if self.thinking_level:
            settings["thinking_config"] = types.ThinkingConfig(thinking_level=self.thinking_level)
        gen_config = types.GenerateContentConfig(**settings)

        last_error = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=gen_config,
                )
                text = response.text
                if text and text.strip():
                    return text.strip()
                last_error = "Empty response (output may have been blocked or cut by the token limit)."
            except errors.APIError as e:
                last_error = str(e)
                if getattr(e, "code", None) not in RETRYABLE_CODES:
                    raise RuntimeError(f"[GeminiLLM] API error: {last_error}") from e
            except Exception as e:  # timeouts and network problems: worth retrying
                last_error = f"{type(e).__name__}: {e}"

            wait = min(2 ** attempt, 60)
            print(f"[GeminiLLM] Attempt {attempt}/{self.max_retries} failed: {last_error} "
                  f"Retrying in {wait}s.")
            time.sleep(wait)

        raise RuntimeError(f"[GeminiLLM] Failed after {self.max_retries} attempts: {last_error}")
