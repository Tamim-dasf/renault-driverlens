import time
import config
from llm_interface import GeminiLLM

llm = GeminiLLM(config.LLM_CONFIG)
start = time.time()
print(llm.generate("Reply with the word OK only."))
print(f"{time.time() - start:.1f} seconds")