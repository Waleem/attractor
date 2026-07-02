#!/usr/bin/env python3
"""Example: Using the OpenAI-Compatible Adapter with Ollama/vLLM/LiteLLM.

Demonstrates how to connect Attractor to any OpenAI-compatible server
(Ollama, vLLM, LiteLLM, LocalAI, llama.cpp, etc.) using the
OpenAICompatAdapter.

Prerequisites:
  # Option A: Ollama (easiest)
  brew install ollama
  ollama serve
  ollama pull llama3.2

  # Option B: vLLM
  pip install vllm
  vllm serve meta-llama/Llama-3.2-1B

Usage:
  # With Ollama (default)
  uv run python examples/openai_compat_ollama.py

  # With vLLM
  uv run python examples/openai_compat_ollama.py \
    --base-url http://localhost:8000/v1 --model meta-llama/Llama-3.2-1B

  # With LiteLLM proxy
  uv run python examples/openai_compat_ollama.py --base-url http://localhost:4000/v1 --model gpt-4
"""

import argparse
import asyncio

from attractor_llm.adapters.base import ProviderConfig
from attractor_llm.adapters.openai_compat import OpenAICompatAdapter
from attractor_llm.client import Client
from attractor_llm.generate import generate


async def main(base_url: str, model: str, api_key: str) -> None:
    print(f"Connecting to: {base_url}")
    print(f"Model: {model}")
    print()

    # Create client with OpenAI-compatible adapter
    client = Client()
    adapter = OpenAICompatAdapter(
        ProviderConfig(
            base_url=base_url,
            api_key=api_key,
        )
    )
    client.register_adapter("local", adapter)

    # --- Test 1: Simple completion ---
    print("=== Test 1: Simple Completion ===")
    try:
        async with client:
            result = await generate(
                client,
                model,
                "What is the capital of France? Reply in one word.",
                provider="local",
            )
        print(f"Response: {result.strip()}")
        print("PASS" if "paris" in result.lower() else "FAIL")
    except Exception as e:
        print(f"ERROR: {e}")
        print("(Is the server running?)")
    print()

    # --- Test 2: System prompt ---
    print("=== Test 2: With System Prompt ===")
    try:
        client2 = Client()
        client2.register_adapter(
            "local",
            OpenAICompatAdapter(
                ProviderConfig(
                    base_url=base_url,
                    api_key=api_key,
                )
            ),
        )
        async with client2:
            result = await generate(
                client2,
                model,
                "Translate 'hello' to Spanish.",
                system="You are a translator. Reply with only the translated word.",
                provider="local",
            )
        print(f"Response: {result.strip()}")
        print("PASS" if "hola" in result.lower() else "FAIL")
    except Exception as e:
        print(f"ERROR: {e}")
    print()

    # --- Test 3: Streaming ---
    print("=== Test 3: Streaming ===")
    try:
        client3 = Client()
        client3.register_adapter(
            "local",
            OpenAICompatAdapter(
                ProviderConfig(
                    base_url=base_url,
                    api_key=api_key,
                )
            ),
        )
        from attractor_llm.generate import stream

        chunks = []
        async with client3:
            result = await stream(
                client3,
                model,
                "Count from 1 to 5, one number per line.",
                provider="local",
            )
            async for chunk in result:
                chunks.append(chunk)
                print(chunk, end="", flush=True)
        print()
        full = "".join(chunks)
        print(f"PASS ({len(chunks)} chunks)" if "3" in full else "FAIL")
    except Exception as e:
        print(f"ERROR: {e}")
    print()

    print("Done. All tests require a running OpenAI-compatible server.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test OpenAI-compatible adapter")
    parser.add_argument(
        "--base-url",
        default="http://localhost:11434/v1",
        help="Base URL of the OpenAI-compatible server (default: Ollama)",
    )
    parser.add_argument(
        "--model",
        default="llama3.2",
        help="Model name (default: llama3.2 for Ollama)",
    )
    parser.add_argument(
        "--api-key",
        default="ollama",
        help="API key (default: 'ollama' -- Ollama doesn't check)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.base_url, args.model, args.api_key))
