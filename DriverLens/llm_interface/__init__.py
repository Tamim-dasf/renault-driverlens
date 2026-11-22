from .base_llm import BaseLLM
from .mock_llm import MockLLM

__all__ = [
    "BaseLLM",
    "GeminiLLM",
    "MockLLM",
]


def __getattr__(name):
    # GeminiLLM is imported only when asked for, so `--dry-run` works
    # even if the google-genai library is not installed yet.
    if name == "GeminiLLM":
        from .gemini_llm import GeminiLLM
        return GeminiLLM
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")