"""The LLM client interface (port) and the normalized types the agent loop speaks.

The agent loop depends only on this module, never on a provider SDK. Concrete
adapters (openai_client.py, and optionally gemini_client.py) implement LLMClient by
translating these normalized types to and from each provider's function-calling API.
This is the seam that keeps the agent vendor-agnostic.
"""

from dataclasses import dataclass
from typing import Any, Protocol

Message = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient(Protocol):
    async def chat_with_tools(
        self, messages: list[Message], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...

    async def complete(self, messages: list[Message]) -> str:
        """A plain text completion with no tools — for summarization, not the agent loop."""
        ...


def system_message(content: str) -> Message:
    return {"role": "system", "content": content}


def user_message(content: str) -> Message:
    return {"role": "user", "content": content}


def assistant_message(text: str | None, tool_calls: list[ToolCall] | None = None) -> Message:
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in (tool_calls or [])
        ],
    }


def tool_result_message(tool_call_id: str, name: str, content: str) -> Message:
    return {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": content}
