import hashlib
import json
from pathlib import Path

import ollama  # import local pour éviter une dépendance circulaire si ce module est importé ailleurs

CACHE_DIR = Path(".llm_cache")
CACHE_DIR.mkdir(exist_ok=True)


def cached_llm_call(user_prompt: str, system_prompt: str, response_schema: dict, model: str) -> dict:
    """
    Calls Ollama, caching the result on disk keyed by (system + prompt + model).
    Avoids repeated slow calls when iterating on the rest of the pipeline.
    """

    cache_key = hashlib.sha256((model + system_prompt + user_prompt).encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.json"

    if cache_file.exists():
        print(f"[cache] Hit for key {cache_key[:8]}...")
        return json.loads(cache_file.read_text())

    print(f"[cache] Miss, calling Ollama (key {cache_key[:8]}...)")
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        format=response_schema,
        options={"temperature": 0},
        keep_alive="30m",
    )
    cache_file.write_text(response["message"]["content"])
    return json.loads(response["message"]["content"])