#!/usr/bin/env python3
"""
Ollama client for local LLM integration.
Uses streaming to eliminate timeout issues on CPU-only machines.
"""

import json
import time
import socket
import urllib.request
import urllib.error
from typing import Optional

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL   = "gemma4:e2b"  # Configurable: phi3:3.8b, phi3:14b, qwen2:14b, mistral, etc.
CHUNK_TIMEOUT   = 200  # seconds to wait between chunks (not total response time)


def generate(
    prompt: str,
    system: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    json_mode: bool = False
) -> str:
    """
    Generate text via Ollama using streaming.

    Streaming means the timeout applies per-chunk, not per-full-response.
    This eliminates TimeoutError on slow CPU-only machines with large prompts.

    Args:
        prompt:      User message
        system:      System prompt
        model:       Ollama model name (must be pulled locally)
        temperature: 0.1 = deterministic, good for documentation
        json_mode:   Force Ollama to return valid JSON (no markdown fences)

    Returns:
        Complete generated text as a single string
    """

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model":   model,
        "stream":  True,          # streaming — no global timeout
        "messages": messages,
        "options": {
            "temperature": temperature,
            "num_ctx":     4096,  # reduced context = faster on CPU
            "num_thread":  max(1, _cpu_thread_count()),
            "num_gpu":     0,     # explicit CPU-only
            "num_batch":   96,   # conservative batch for low RAM
            "top_p":       0.95,
            "top_k":       40,
        }
    }

    if json_mode:
        payload["format"] = "json"

    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        full_response = []
        token_count   = 0

        with urllib.request.urlopen(req, timeout=CHUNK_TIMEOUT) as response:
            for raw_line in response:
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    chunk = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                token = chunk.get("message", {}).get("content", "")
                if token:
                    full_response.append(token)
                    token_count += 1

                    # Progress indicator every 100 tokens
                    if token_count % 100 == 0:
                        print(f"    ↳ {token_count} tokens...", end="\r")

                if chunk.get("done", False):
                    break

        print(f"    ↳ Done — {token_count} tokens generated.      ")
        return "".join(full_response)

    except urllib.error.URLError as e:
        if "Connection refused" in str(e) or "nodename nor servname" in str(e):
            raise ConnectionError(
                f"Cannot connect to Ollama at {OLLAMA_BASE_URL}.\n"
                "  → Run: ollama serve"
            )
        raise ConnectionError(f"Ollama connection error: {e}")

    except urllib.error.HTTPError as e:
        raise ConnectionError(f"Ollama HTTP error {e.code}: {e.reason}")

    except (TimeoutError, socket.timeout):
        raise TimeoutError(
            f"No response chunk received in {CHUNK_TIMEOUT}s.\n"
            "  → Ollama may be overloaded. Try: ollama ps"
        )


def generate_with_retry(
    prompt: str,
    system: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    json_mode: bool = False,
    max_retries: int = 3
) -> str:
    """
    Generate with exponential backoff retry.
    Wait times: 2s → 4s → 8s between attempts.
    """

    last_error = None

    for attempt in range(max_retries):
        try:
            return generate(
                prompt=prompt,
                system=system,
                model=model,
                temperature=temperature,
                json_mode=json_mode
            )
        except Exception as e:
            last_error = e
            if attempt == max_retries - 1:
                break
            wait = 2 ** (attempt + 1)  # 2, 4, 8
            print(f"  [RETRY] Attempt {attempt + 1}/{max_retries} failed: {e}")
            print(f"  [RETRY] Waiting {wait}s...")
            time.sleep(wait)

    raise last_error


def check_connection(model: str = DEFAULT_MODEL) -> bool:
    """Check Ollama is running and model is available."""
    try:
        with urllib.request.urlopen(
            f"{OLLAMA_BASE_URL}/api/tags", timeout=5
        ) as response:
            data        = json.loads(response.read().decode("utf-8"))
            model_names = [m["name"] for m in data.get("models", [])]
            available   = any(model in m for m in model_names)

            if not available:
                print(f"[WARN] Model '{model}' not found.")
                print(f"       Available: {', '.join(model_names) or 'none'}")
                print(f"       Pull it:   ollama pull {model}")
                return False
            return True

    except urllib.error.URLError:
        print(f"[ERROR] Cannot reach Ollama at {OLLAMA_BASE_URL}")
        print("        Start it: ollama serve")
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def _cpu_thread_count() -> int:
    """Return physical CPU thread count for Ollama num_thread option."""
    try:
        import multiprocessing
        return multiprocessing.cpu_count()
    except Exception:
        return 4


if __name__ == "__main__":
    print("=" * 60)
    print("  Ollama Connection Test")
    print("=" * 60)

    if check_connection():
        print("[OK] Ollama is running.\n")
        response = generate(
            prompt="Explain Power BI in one sentence.",
            system="You are a BI expert. Be concise.",
        )
        print(f"[RESPONSE]\n{response}")
    else:
        print("[FAIL] Fix the errors above and retry.")