from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx

# 테스트에서 외부 경계(httpx transport)를 주입할 수 있도록 둔 모듈 수준 훅이다.
_TRANSPORT: httpx.AsyncBaseTransport | None = None


class LLMNotConfigured(RuntimeError):
    pass


class LLMStreamError(RuntimeError):
    pass


def config() -> dict[str, str] | None:
    base_url = os.environ.get("KP_LLM_BASE_URL", "").strip().rstrip("/")
    # Knowledge Model이 나중(Phase 4)에 따로 지정되지 않으면 Chat 모델을 그대로 쓴다.
    chat_model = os.environ.get("KP_CHAT_MODEL", "").strip() or os.environ.get(
        "KP_KNOWLEDGE_MODEL", ""
    ).strip()
    if not base_url or not chat_model:
        return None
    return {
        "base_url": base_url,
        "api_key": os.environ.get("KP_LLM_API_KEY", "").strip(),
        "chat_model": chat_model,
        "knowledge_model": os.environ.get("KP_KNOWLEDGE_MODEL", "").strip() or chat_model,
    }


def status() -> dict[str, Any]:
    cfg = config()
    if cfg is None:
        return {
            "configured": False,
            "model": None,
            "knowledge_model": None,
            "base_host": None,
        }
    from urllib.parse import urlsplit

    return {
        "configured": True,
        "model": cfg["chat_model"],
        "knowledge_model": cfg["knowledge_model"],
        "base_host": urlsplit(cfg["base_url"]).netloc,
    }


def _headers(cfg: dict[str, str]) -> dict[str, str]:
    # 로컬 호환 API는 키가 없을 수 있으므로 있을 때만 Authorization을 붙인다.
    h = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        h["Authorization"] = f"Bearer {cfg['api_key']}"
    return h


async def complete(messages: list[dict]) -> dict[str, Any]:
    """비스트리밍 단발 생성. Phase 4의 구조화 생성이 이 경로를 확장할 수 있게 둔 최소 형태."""
    cfg = config()
    if cfg is None:
        raise LLMNotConfigured("LLM provider가 설정되지 않았습니다")
    payload = {"model": cfg["chat_model"], "messages": messages, "stream": False}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), transport=_TRANSPORT) as client:
        resp = await client.post(
            f"{cfg['base_url']}/chat/completions", json=payload, headers=_headers(cfg)
        )
    if resp.status_code != 200:
        raise LLMStreamError(f"LLM API 오류 (HTTP {resp.status_code})")
    try:
        obj = resp.json()
        choice = (obj.get("choices") or [None])[0]
        if choice is None:
            raise ValueError("empty choices")
        content = (choice.get("message") or {}).get("content")
        if not isinstance(content, str):
            raise ValueError("no content")
        return {"role": "assistant", "content": content, "finish_reason": choice.get("finish_reason")}
    except (ValueError, KeyError, TypeError) as e:
        raise LLMStreamError(f"LLM 응답 형식 오류: {e}") from e


async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    """OpenAI 호환 chat/completions(stream:true)에서 텍스트 델타만 순서대로 yield한다.

    role-only 청크, 빈 choices, reasoning/tool_call 청크는 출력 텍스트가 아니므로 건너뛴다.
    [DONE] 없이 스트림이 끝나거나 형식이 깨진 청크가 오면 성공으로 취급하지 않고 예외를 낸다.
    """
    cfg = config()
    if cfg is None:
        raise LLMNotConfigured("LLM provider가 설정되지 않았습니다")
    payload = {"model": cfg["chat_model"], "messages": messages, "stream": True}
    url = f"{cfg['base_url']}/chat/completions"
    done_seen = False
    buf = b""
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30.0), transport=_TRANSPORT) as client:
        try:
            async with client.stream(
                "POST", url, json=payload, headers=_headers(cfg)
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread())[:300]
                    raise LLMStreamError(f"LLM API 오류 (HTTP {resp.status_code}): {body.decode('utf-8', 'replace')}")
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    while True:
                        # SSE 이벤트는 빈 줄로 구분된다. \r\n도 허용한다.
                        for sep in (b"\n\n", b"\r\n\r\n", b"\r\r"):
                            idx = buf.find(sep)
                            if idx >= 0:
                                break
                        else:
                            break
                        block, buf = buf[:idx], buf[idx + len(sep):]
                        texts, done = _process_block(block)
                        for text in texts:
                            yield text
                        if done:
                            done_seen = True
                            return
        except httpx.HTTPError as e:
            raise LLMStreamError(f"LLM 스트림 오류: {e}") from e
    if not done_seen and buf.strip():
        # 스트림이 [DONE] 없이 끝났는데 버퍼에 남은 내용이 있으면 형식 오류다.
        raise LLMStreamError("스트림이 [DONE] 없이 종료되었습니다")
    if not done_seen:
        raise LLMStreamError("스트림이 [DONE] 없이 종료되었습니다")


def _process_block(block: bytes) -> tuple[list[str], bool]:
    texts: list[str] = []
    done = False
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            done = True
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError as e:
            raise LLMStreamError(f"SSE data가 JSON이 아닙니다: {data[:80]!r}") from e
        if not isinstance(obj, dict):
            raise LLMStreamError("SSE data가 객체가 아닙니다")
        choices = obj.get("choices")
        if not choices:  # role-only 청크나 keep-alive 이벤트는 텍스트가 없다
            continue
        for choice in choices:
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                raise LLMStreamError("delta 형식 오류")
            content = delta.get("content")
            if content:
                if not isinstance(content, str):
                    raise LLMStreamError("content 형식 오류")
                texts.append(content)
            # finish_reason, tool_calls, reasoning은 출력 텍스트가 아니다.
    return texts, done
