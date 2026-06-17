from __future__ import annotations


class AnthropicLLM:
    """Anthropic Claude — uses the Messages API."""

    def __init__(self, api_key: str, model: str, temperature: float | None = None) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._temperature = temperature

    async def complete(self, prompt: str) -> str:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        temperature = getattr(self, "_temperature", None)
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = await self._client.messages.create(**kwargs)
        # Extract the first text block; content may include tool_use or other block types.
        for block in response.content:
            if block.type == "text":
                return block.text
        raise RuntimeError(
            f"Anthropic returned no text block (stop_reason={response.stop_reason}, "
            f"block_types={[b.type for b in response.content]})"
        )
