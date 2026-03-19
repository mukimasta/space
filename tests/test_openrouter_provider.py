from __future__ import annotations

import httpx
import pytest

from space.llm.openrouter import OpenRouterProvider


@pytest.mark.asyncio
async def test_generate_parses_text_content() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "hello",
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="x", model="m", client=client)
        result = await provider.generate([{"role": "user", "content": "hi"}])

    assert result.content == "hello"
    assert result.tool_calls is None
    assert result.usage is None


@pytest.mark.asyncio
async def test_generate_parses_tool_calls() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":"SPACE.md"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="x", model="m", client=client)
        result = await provider.generate(
            [{"role": "user", "content": "read"}],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        )

    assert result.content is None
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "SPACE.md"}


@pytest.mark.asyncio
async def test_stream_yields_incremental_tokens() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        sse_body = (
            'data: {"choices":[{"delta":{"content":"hello "}}]}\n'
            'data: {"choices":[{"delta":{"content":"world"}}]}\n'
            "data: [DONE]\n"
        )
        return httpx.Response(
            200,
            text=sse_body,
            headers={"content-type": "text/event-stream"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="x", model="m", client=client)
        chunks: list[str] = []
        async for token in provider.stream([{"role": "user", "content": "hi"}]):
            chunks.append(token)

    assert "".join(chunks) == "hello world"


@pytest.mark.asyncio
async def test_generate_parses_usage() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "cost": 0.0012,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="x", model="m", client=client)
        result = await provider.generate([{"role": "user", "content": "hi"}])

    assert result.usage is not None
    assert result.usage.total_tokens == 15
    assert result.usage.cost_usd == 0.0012


@pytest.mark.asyncio
async def test_stream_stores_last_usage_when_present() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        sse_body = (
            'data: {"choices":[{"delta":{"content":"hello"}}]}\n'
            'data: {"usage":{"prompt_tokens":4,"completion_tokens":3,"total_tokens":7,"cost":0.0003}}\n'
            "data: [DONE]\n"
        )
        return httpx.Response(
            200,
            text=sse_body,
            headers={"content-type": "text/event-stream"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="x", model="m", client=client)
        chunks: list[str] = []
        async for token in provider.stream([{"role": "user", "content": "hi"}]):
            chunks.append(token)

    assert "".join(chunks) == "hello"
    assert provider.last_usage is not None
    assert provider.last_usage.total_tokens == 7


@pytest.mark.asyncio
async def test_generate_raises_clear_error_when_api_key_missing() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="  ", model="m", client=client)
        with pytest.raises(ValueError, match="Missing API key"):
            await provider.generate([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_list_models_parses_openrouter_payload() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "openai/gpt-4o-mini"},
                    {"id": "openai/gpt-4o"},
                    {"id": "openai/gpt-4o-mini"},
                    {"name": "missing-id"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key="x", model="m", client=client)
        models = await provider.list_models()

    assert models == ["openai/gpt-4o-mini", "openai/gpt-4o"]
