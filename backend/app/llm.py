from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator, Literal, Protocol
from urllib.parse import urlsplit

import httpx


class LLMNotConfigured(RuntimeError):
    pass


class LLMStreamError(RuntimeError):
    pass


class LLMInterrupted(LLMStreamError):
    pass


class LLMClient(Protocol):
    def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        """본문만 전달한다. 정상 완료 외에는 LLMInterrupted/LLMStreamError,
        설정이 없거나 지원되지 않으면 LLMNotConfigured로 실패한다.
        """
        ...

    async def complete(self, messages: list[dict], json_mode: bool = False) -> str:
        """정상 완료 본문을 반환하며 스트리밍과 같은 예외 계약을 따른다."""
        ...


def config() -> dict[str, str] | None:
    base_url = os.environ.get("KP_LLM_BASE_URL", "").strip().rstrip("/")
    chat_model = os.environ.get("KP_CHAT_MODEL", "").strip()
    if not base_url or not chat_model:
        return None
    return {
        "reasoning_effort": os.environ.get("KP_LLM_REASONING_EFFORT", ""),
        "base_url": base_url,
        "api_key": os.environ.get("KP_LLM_API_KEY", "").strip(),
        "chat_model": chat_model,
        "knowledge_model": os.environ.get("KP_KNOWLEDGE_MODEL", "").strip() or chat_model,
    }


def status() -> dict[str, Any]:
    cfg = config()
    try:
        get_client("chat")
        configured = True
    except LLMNotConfigured:
        configured = False
    return {
        "provider": os.environ.get("KP_LLM_PROVIDER", "openai-compatible").strip(),
        "configured": configured,
        "model": cfg["chat_model"] if cfg else None,
        "knowledge_model": cfg["knowledge_model"] if cfg else None,
        # URL 사용자 정보에는 인증 값이 들어갈 수 있어 hostname만 공개한다.
        "base_host": urlsplit(cfg["base_url"]).hostname if cfg else None,
    }


def get_client(role: Literal["chat", "knowledge"]) -> LLMClient:
    provider = os.environ.get("KP_LLM_PROVIDER", "openai-compatible").strip()
    if provider != "openai-compatible":
        raise LLMNotConfigured("KP_LLM_PROVIDER에 지원하지 않는 Provider가 지정되었습니다.")
    cfg = config()
    if cfg is None:
        raise LLMNotConfigured("LLM provider 미설정: KP_LLM_BASE_URL / KP_CHAT_MODEL을 지정하세요.")
    return OpenAICompatibleClient(cfg, cfg[f"{role}_model"])


class OpenAICompatibleClient:
    def __init__(self, config: dict[str, str], model: str):
        self._config = config
        self._model = model

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        cfg = self._config
        headers = {"Content-Type": "application/json"}
        if cfg["api_key"]:
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        payload = {"model": self._model, "messages": messages, "stream": True}
        if cfg["reasoning_effort"]:
            payload["reasoning_effort"] = cfg["reasoning_effort"]
        finish_reason = None
        content_seen = False
        # 무응답 연결도 중단으로 기록할 수 있도록 읽기 대기 시간을 제한한다.
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
            try:
                async with client.stream(
                    "POST", f"{cfg['base_url']}/chat/completions", json=payload, headers=headers
                ) as resp:
                    if resp.status_code != 200:
                        # Provider 본문/예외에는 키와 요청 주소가 포함될 수 있어 전달하지 않는다.
                        raise LLMStreamError(f"LLM API 오류 (HTTP {resp.status_code})")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            if finish_reason != "stop":
                                raise LLMInterrupted("LLM 응답이 정상 종료되지 않았습니다 (종료 이유가 stop이 아님).")
                            if not content_seen:
                                raise LLMStreamError("LLM이 빈 응답을 반환했습니다.")
                            return
                        try:
                            obj = json.loads(data)
                            if not isinstance(obj, dict) or "error" in obj:
                                raise ValueError
                            choices = obj.get("choices") or []
                            for choice in choices:
                                if choice.get("index", 0) != 0:
                                    continue
                                delta = choice.get("delta") or {}
                                content = delta.get("content")
                                if content is not None and not isinstance(content, str):
                                    raise ValueError
                                if content:
                                    content_seen = content_seen or bool(content.strip())
                                    yield content
                                reason = choice.get("finish_reason")
                                if reason is not None:
                                    finish_reason = reason
                        except (ValueError, TypeError, AttributeError) as e:
                            raise LLMStreamError("LLM 스트림 응답 형식이 올바르지 않습니다.") from e
            except httpx.HTTPError as e:
                raise LLMInterrupted("LLM 스트림 연결이 끊겼거나 응답 시간이 초과되었습니다.") from e
        raise LLMInterrupted("LLM 스트림이 [DONE] 없이 종료되었습니다.")

    async def complete(self, messages: list[dict], json_mode: bool = False) -> str:
        cfg = self._config
        headers = {"Content-Type": "application/json"}
        if cfg["api_key"]:
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        payload = {"model": self._model, "messages": messages, "stream": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if cfg["reasoning_effort"]:
            payload["reasoning_effort"] = cfg["reasoning_effort"]
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
                response = await client.post(f"{cfg['base_url']}/chat/completions", json=payload, headers=headers)
            if response.status_code != 200:
                raise LLMStreamError(f"LLM API 오류 (HTTP {response.status_code})")
            try:
                choice = response.json()["choices"][0]
                content = choice["message"].get("content")
                if choice.get("finish_reason") != "stop":
                    raise LLMInterrupted("LLM 응답이 정상 종료되지 않았습니다.")
                if not isinstance(content, str) or not content.strip():
                    raise LLMStreamError("LLM이 빈 응답을 반환했습니다.")
                return content
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
                raise LLMStreamError("LLM 응답 형식이 올바르지 않습니다.") from e
        except httpx.HTTPError as e:
            raise LLMInterrupted("LLM 연결이 끊겼거나 응답 시간이 초과되었습니다.") from e
