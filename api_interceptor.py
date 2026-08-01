"""
API Interceptor - Automatically tracks token usage from AI API responses.
Supports OpenAI-compatible APIs (AGY, Codex), DeepSeek, and Mimo.
"""

import functools
import logging
from typing import Optional, Callable
from token_tracker import tracker

logger = logging.getLogger("api_interceptor")


def track_openai(client, provider: str = "AGY"):
    """Wrap an OpenAI client to automatically track token usage."""
    original_create = client.chat.completions.create

    @functools.wraps(original_create)
    def tracked_create(*args, **kwargs):
        response = original_create(*args, **kwargs)
        if hasattr(response, "usage") and response.usage:
            tracker.add_usage(
                provider,
                getattr(response.usage, "prompt_tokens", 0) or 0,
                getattr(response.usage, "completion_tokens", 0) or 0
            )
        return response

    client.chat.completions.create = tracked_create
    return client


def track_deepseek(client, provider: str = "DeepSeek"):
    """Wrap a DeepSeek client."""
    return track_openai(client, provider=provider)


def track_mimo(client, provider: str = "Mimo"):
    """Wrap a Mimo client."""
    return track_openai(client, provider=provider)


def track_usage_decorator(provider: str):
    """Decorator to track token usage from custom API functions."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            if isinstance(result, dict) and "usage" in result:
                usage = result["usage"]
                tracker.add_usage(
                    provider,
                    usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                    usage.get("completion_tokens", usage.get("output_tokens", 0))
                )
            return result
        return wrapper
    return decorator
