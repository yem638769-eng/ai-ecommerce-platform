"""LLM Provider 抽象层：统一对接 Ollama / OpenAI 兼容 API。

内部统一使用 OpenAI 格式的消息与工具定义，OllamaProvider 负责格式转换：
- messages: [{"role": "system|user|assistant|tool", "content": str, ...}]
- assistant.tool_calls: [{"id", "type": "function", "function": {"name", "arguments"(JSON字符串)}}]
- tool 消息: {"role": "tool", "tool_call_id", "content"}
- tools: [{"type": "function", "function": {"name", "description", "parameters"(JSON Schema)}}]
"""
import json
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx

from app.core.config import settings


class LLMError(Exception):
    """LLM 服务调用异常。"""


class LLMProvider(ABC):
    chat_model: str
    embed_model: str

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        json_mode: bool = False,
        temperature: float = 0.7,
    ) -> dict:
        """非流式对话。返回 {"content": str, "tool_calls": list}（OpenAI 格式，可为空列表）。"""

    @abstractmethod
    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[dict]:
        """流式对话：逐个 yield {"delta": str}；若模型请求工具则 yield {"tool_calls": [...]}；结尾 yield {"done": True}。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化。"""

    @abstractmethod
    async def health(self) -> bool:
        """服务连通性检测。"""


def _normalize_tool_arguments(arguments) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments or {}, ensure_ascii=False)


class OllamaProvider(LLMProvider):
    def __init__(self):
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.chat_model = settings.ollama_chat_model
        self.embed_model = settings.ollama_embed_model
        self.timeout = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0)

    @staticmethod
    def _to_ollama_messages(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        tool_name_by_id: dict[str, str] = {}
        for m in messages:
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                calls = []
                for c in m["tool_calls"]:
                    fn = c.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    tool_name_by_id[c.get("id") or fn.get("name", "tool")] = fn.get("name", "tool")
                    calls.append({"function": {"name": fn.get("name", ""), "arguments": args}})
                out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
            elif role == "tool":
                out.append({
                    "role": "tool",
                    "tool_name": tool_name_by_id.get(m.get("tool_call_id", ""), "tool"),
                    "content": m.get("content", ""),
                })
            else:
                out.append({"role": role, "content": m.get("content") or ""})
        return out

    @staticmethod
    def _from_ollama_tool_calls(tool_calls: list | None) -> list[dict]:
        result = []
        for i, c in enumerate(tool_calls or []):
            fn = c.get("function") or {}
            result.append({
                "id": c.get("id") or f"call_{i}",
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": _normalize_tool_arguments(fn.get("arguments")),
                },
            })
        return result

    async def chat(self, messages, tools=None, json_mode=False, temperature=0.7) -> dict:
        payload = {
            "model": self.chat_model,
            "messages": self._to_ollama_messages(messages),
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama 调用失败: {e}") from e
        msg = data.get("message") or {}
        return {
            "content": msg.get("content") or "",
            "tool_calls": self._from_ollama_tool_calls(msg.get("tool_calls")),
        }

    async def chat_stream(self, messages, tools=None, temperature=0.7):
        payload = {
            "model": self.chat_model,
            "messages": self._to_ollama_messages(messages),
            "stream": True,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools
        tool_calls: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg = chunk.get("message") or {}
                        if msg.get("content"):
                            yield {"delta": msg["content"]}
                        if msg.get("tool_calls"):
                            tool_calls = self._from_ollama_tool_calls(msg["tool_calls"])
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama 流式调用失败: {e}") from e
        if tool_calls:
            yield {"tool_calls": tool_calls}
        yield {"done": True}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.embed_model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0)) as client:
                resp = await client.post(f"{self.base_url}/api/embed", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama 向量化失败: {e}") from e
        embeddings = data.get("embeddings") or []
        if len(embeddings) != len(texts):
            raise LLMError("Embedding 数量与输入不匹配")
        return embeddings

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


class OpenAIProvider(LLMProvider):
    def __init__(self):
        if not settings.openai_api_key:
            raise LLMError("LLM_PROVIDER=openai 但未配置 OPENAI_API_KEY")
        self.base_url = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = settings.openai_api_key
        self.chat_model = settings.openai_chat_model
        self.embed_model = settings.openai_embed_model
        self.timeout = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def chat(self, messages, tools=None, json_mode=False, temperature=0.7) -> dict:
        payload = {"model": self.chat_model, "messages": messages, "temperature": temperature}
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise LLMError(f"OpenAI 兼容接口调用失败: {e}") from e
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        tool_calls = [
            {
                "id": c.get("id") or f"call_{i}",
                "type": "function",
                "function": {
                    "name": (c.get("function") or {}).get("name", ""),
                    "arguments": _normalize_tool_arguments((c.get("function") or {}).get("arguments")),
                },
            }
            for i, c in enumerate(msg.get("tool_calls") or [])
        ]
        return {"content": msg.get("content") or "", "tool_calls": tool_calls}

    async def chat_stream(self, messages, tools=None, temperature=0.7):
        payload = {"model": self.chat_model, "messages": messages, "stream": True, "temperature": temperature}
        if tools:
            payload["tools"] = tools
        tool_calls_acc: dict[int, dict] = {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                        if delta.get("content"):
                            yield {"delta": delta["content"]}
                        for c in delta.get("tool_calls") or []:
                            idx = c.get("index", 0)
                            slot = tool_calls_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            fn = c.get("function") or {}
                            slot["id"] = slot["id"] or c.get("id") or f"call_{idx}"
                            slot["name"] = slot["name"] or fn.get("name", "")
                            slot["arguments"] += fn.get("arguments") or ""
        except httpx.HTTPError as e:
            raise LLMError(f"OpenAI 兼容接口流式调用失败: {e}") from e
        if tool_calls_acc:
            yield {
                "tool_calls": [
                    {
                        "id": v["id"],
                        "type": "function",
                        "function": {"name": v["name"], "arguments": v["arguments"] or "{}"},
                    }
                    for _, v in sorted(tool_calls_acc.items())
                ]
            }
        yield {"done": True}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.embed_model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/embeddings", json=payload, headers=self._headers()
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise LLMError(f"OpenAI 兼容接口向量化失败: {e}") from e
        ordered = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
        embeddings = [d.get("embedding") for d in ordered]
        if len(embeddings) != len(texts) or any(e is None for e in embeddings):
            raise LLMError("Embedding 数量与输入不匹配")
        return embeddings

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


_llm: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _llm
    if _llm is None:
        _llm = OllamaProvider() if settings.llm_provider == "ollama" else OpenAIProvider()
    return _llm
