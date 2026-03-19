from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from space.llm.base import ApiMessage, LLMProvider, LLMUsage
from space.tool.base import Tool


class AgentLoopLimitError(RuntimeError):
    pass


class AgentInterruptedError(RuntimeError):
    pass


class Agent(Protocol):
    async def run(self, messages: list[ApiMessage], tools: list[Tool], llm: LLMProvider) -> str: ...


def _tool_call_to_api(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


@dataclass(slots=True)
class AgentLoopSettings:
    max_iterations: int = 12
    should_stop: Callable[[], bool] | None = None
    finish_tool_name: str | None = None
    on_usage: Callable[[LLMUsage | None], None] | None = None
    on_tool_call: Callable[[str, dict[str, Any], str], Awaitable[None] | None] | None = None


async def agent_loop(
    llm: LLMProvider,
    messages: list[ApiMessage],
    tools: list[Tool],
    settings: AgentLoopSettings | None = None,
) -> str:
    cfg = settings or AgentLoopSettings()
    tool_defs = [tool.to_api_dict() for tool in tools]
    tool_map = {tool.name: tool for tool in tools}

    for _ in range(cfg.max_iterations):
        if cfg.should_stop and cfg.should_stop():
            raise AgentInterruptedError("agent loop interrupted by stop signal")

        response = await llm.generate(messages, tools=tool_defs or None)
        if cfg.on_usage:
            cfg.on_usage(response.usage)
        if not response.tool_calls:
            return response.content or ""

        assistant_message: dict[str, Any] = {"role": "assistant", "content": response.content}
        assistant_message["tool_calls"] = [
            _tool_call_to_api(call.id, call.name, call.arguments) for call in response.tool_calls
        ]
        messages.append(assistant_message)

        finish_result: str | None = None
        for call in response.tool_calls:
            tool = tool_map.get(call.name)
            if tool is None:
                result = f"Tool '{call.name}' is not available."
            else:
                try:
                    result = await tool.execute(**call.arguments)
                except Exception as exc:  # noqa: BLE001
                    result = f"{type(exc).__name__}: {exc}"

            if cfg.finish_tool_name and call.name == cfg.finish_tool_name:
                finish_result = result

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )

            if cfg.on_tool_call:
                cb = cfg.on_tool_call(call.name, call.arguments, result)
                if cb is not None:
                    await cb

        if finish_result is not None:
            return finish_result

    raise AgentLoopLimitError(f"Agent loop exceeded iteration limit: {cfg.max_iterations}")
