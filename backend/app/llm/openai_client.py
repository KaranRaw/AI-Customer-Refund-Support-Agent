"""OpenAI adapter implementing the LLMClient port.

Translates the loop's normalized messages into OpenAI's chat-completions format and
its tool-call responses back into LLMResponse. Swapping providers means adding a
sibling adapter, not touching the loop.
"""

import json
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.llm.client import LLMResponse, Message, ToolCall


def _to_openai_message(message: Message) -> dict[str, Any]:
    role = message["role"]
    if role == "assistant":
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            return {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                    for call in tool_calls
                ],
            }
        return {"role": "assistant", "content": message.get("content")}
    if role == "tool":
        return {"role": "tool", "tool_call_id": message["tool_call_id"], "content": message["content"]}
    return {"role": role, "content": message["content"]}


class OpenAIClient:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self._model = model or settings.llm_model

    async def chat_with_tools(
        self, messages: list[Message], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[_to_openai_message(m) for m in messages],
            tools=tools,
            tool_choice="auto",
        )
        message = response.choices[0].message

        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))

        usage = response.usage
        return LLMResponse(
            text=message.content,
            tool_calls=tool_calls,
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )

    async def complete(self, messages: list[Message]) -> str:
        """Plain completion (no tools) — used for case summaries."""
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[_to_openai_message(m) for m in messages],
        )
        return response.choices[0].message.content or ""
