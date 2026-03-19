"""KKSJ LLM provider. Uses OpenAI-compatible API with Bearer auth."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx

from space.llm.base import ApiMessage, LLMResponse, LLMUsage, ToolCall, ToolDef


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or "").strip() or default


class KKSJProvider:
    """KKSJ API provider. Config from env (KKSJ_API_KEY, KKSJ_BASE_URL, KKSJ_MODEL) or constructor args."""

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = (api_key or _env("KKSJ_API_KEY")).strip()
        self._model = (model or _env("KKSJ_MODEL", "gemini-3-flash-preview")).strip()
        self._base_url = (base_url or _env("KKSJ_BASE_URL")).rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self.last_usage: LLMUsage | None = None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ValueError(
                "Missing KKSJ API key. Set KKSJ_API_KEY in env or api_key in ~/.space/config.json"
            )
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_content(message: dict[str, Any]) -> str | None:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "".join(chunks) if chunks else None
        return None

    @staticmethod
    def _parse_arguments(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            data = raw.strip()
            if not data:
                return {}
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                return {"raw": raw}
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        return {}

    @classmethod
    def _extract_tool_calls(cls, message: dict[str, Any]) -> list[ToolCall] | None:
        raw_calls = message.get("tool_calls")
        if not isinstance(raw_calls, list) or not raw_calls:
            return None

        tool_calls: list[ToolCall] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                continue
            fn = raw_call.get("function")
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            if not isinstance(name, str) or not name:
                continue
            call_id = raw_call.get("id")
            if not isinstance(call_id, str):
                call_id = f"tool_{len(tool_calls)}"
            arguments = cls._parse_arguments(fn.get("arguments"))
            tool_calls.append(ToolCall(id=call_id, name=name, arguments=arguments))

        return tool_calls or None

    @staticmethod
    def _extract_usage(payload: dict[str, Any]) -> LLMUsage | None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return None

        def to_int(name: str) -> int:
            value = usage.get(name, 0)
            return int(value) if isinstance(value, (int, float)) else 0

        prompt_tokens = to_int("prompt_tokens")
        completion_tokens = to_int("completion_tokens")
        total_tokens = to_int("total_tokens")
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens

        return LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=None,
        )

    def _build_payload(self, messages: list[ApiMessage], tools: list[ToolDef] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self._model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    async def generate(
        self,
        messages: list[ApiMessage],
        tools: list[ToolDef] | None = None,
    ) -> LLMResponse:
        url = f"{self._base_url}/chat/completions"
        payload = self._build_payload(messages, tools)
        response = await self._client.post(
            url, json=payload, headers=self._headers(), timeout=self._timeout
        )
        response.raise_for_status()
        body = response.json()
        usage = self._extract_usage(body)
        self.last_usage = usage

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return LLMResponse(content=None, tool_calls=None, usage=usage)
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        if not isinstance(message, dict):
            return LLMResponse(content=None, tool_calls=None, usage=usage)

        content = self._extract_content(message)
        tool_calls = self._extract_tool_calls(message)
        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage)

    async def stream(self, messages: list[ApiMessage]) -> AsyncIterator[str]:
        url = f"{self._base_url}/chat/completions"
        payload = self._build_payload(messages)
        payload["stream"] = True
        self.last_usage = None

        async with self._client.stream(
            "POST",
            url,
            json=payload,
            headers=self._headers(),
            timeout=self._timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = self._extract_usage(event)
                if usage is not None:
                    self.last_usage = usage
                choices = event.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                first = choices[0]
                if not isinstance(first, dict):
                    continue
                if first.get("finish_reason") == "stop":
                    break
                delta = first.get("delta")
                if not isinstance(delta, dict):
                    continue
                content = delta.get("content")
                if isinstance(content, str) and content:
                    yield content
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            text = item.get("text")
                            if isinstance(text, str) and text:
                                yield text

    async def list_models(self) -> list[str]:
        url = f"{self._base_url}/models"
        response = await self._client.get(
            url, headers=self._headers(), timeout=self._timeout
        )
        response.raise_for_status()
        body = response.json()
        data = body.get("data")
        if not isinstance(data, list):
            return []

        models: list[str] = []
        seen: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if not isinstance(model_id, str):
                continue
            clean = model_id.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            models.append(clean)
        return models
