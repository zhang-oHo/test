from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.config import Settings

LLMRole = Literal["router", "generator", "judge"]


@runtime_checkable
class LLMBackend(Protocol):
    async def complete(self, prompt: str) -> str: ...


@runtime_checkable
class EmbedBackend(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...

_PROVIDER_KEY_MAP = {
    "openai": "openai_api_key",
    "claude": "anthropic_api_key",
    "gemini": "gemini_api_key",
    "github_copilot": "github_copilot_token",
}


def has_llm_configured(settings: Settings) -> bool:
    attr = _PROVIDER_KEY_MAP.get(settings.ai_provider)
    return bool(attr and getattr(settings, attr, ""))


def build_llm(settings: Settings, role: LLMRole) -> LLMBackend:
    """Return an LLM instance matching the active ai_provider and role model.

    "judge" role uses settings.judge_model when set; falls back to router_model.
    Router and judge roles use temperature=0.0 for deterministic outputs.
    """
    if role == "router":
        model = settings.router_model
    elif role == "judge":
        model = settings.judge_model or settings.router_model
    else:
        model = settings.generator_model
    provider = settings.ai_provider
    temperature = 0.0 if role in ("router", "judge") else None

    if provider == "openai":
        from app.ai.providers.openai_provider import OpenAILLM
        return OpenAILLM(settings, model, temperature=temperature)

    if provider == "claude":
        from app.ai.providers.anthropic_provider import AnthropicLLM
        return AnthropicLLM(settings.anthropic_api_key, model, temperature=temperature)

    if provider == "gemini":
        from app.ai.providers.gemini_provider import GeminiLLM
        return GeminiLLM(settings.gemini_api_key, model, temperature=temperature)

    if provider == "github_copilot":
        from app.ai.providers.openai_provider import OpenAIChatLLM
        return OpenAIChatLLM(
            settings.github_copilot_token,
            settings.github_copilot_base_url,
            model,
            temperature=temperature,
        )

    raise ValueError(
        f"Unknown AI provider: {provider!r}. "
        "Valid values: openai | claude | gemini | github_copilot"
    )


def build_embedder(settings: Settings) -> EmbedBackend:
    """Return an embedder instance matching the active embedding_provider."""
    provider = settings.embedding_provider

    if provider == "openai":
        from app.ai.providers.openai_provider import OpenAIEmbedder
        return OpenAIEmbedder(settings)

    if provider == "gemini":
        from app.ai.providers.gemini_provider import GeminiEmbedder
        return GeminiEmbedder(settings.gemini_api_key, settings.embedding_model)

    if provider == "huggingface":
        from app.ai.providers.huggingface_provider import HuggingFaceEmbedder
        return HuggingFaceEmbedder(settings)

    raise ValueError(
        f"Unknown embedding provider: {provider!r}. "
        "Valid values: openai | gemini | huggingface"
    )
