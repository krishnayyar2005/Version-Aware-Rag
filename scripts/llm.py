"""Single entry point for LLM calls (Gemini). Swap providers here only."""
import os
import time

DEFAULT_MODEL = "gemini-3.8-flash"
_client = None


def _get_client():
    global _client
    if _client is None:
        from dotenv import load_dotenv
        from google import genai
        load_dotenv()
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def generate(prompt, system=None, temperature=0.0, retries=4):
    """Return model text. Retries on rate limit / transient errors (429, 500, 503)."""
    from google.genai import types
    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    cfg = types.GenerateContentConfig(system_instruction=system, temperature=temperature)
    for i in range(retries):
        try:
            resp = _get_client().models.generate_content(model=model, contents=prompt, config=cfg)
            return resp.text or ""
        except Exception as e:
            code = getattr(e, "code", None)
            if code in (429, 500, 503) and i < retries - 1:
                wait = 15 * (2 ** i)
                print(f"  [llm] error {code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise


if __name__ == "__main__":
    print(generate("Reply with the single word: ready"))
