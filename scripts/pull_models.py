"""首次启动时拉取 Ollama 模型（幂等，可后台运行）。

用法：python scripts/pull_models.py
- Ollama 未就绪：等待重试；仍不可用则警告退出（不阻塞 API 启动，AI 功能自动降级）
- 模型已存在：跳过
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")


async def wait_ollama(client: httpx.AsyncClient, tries: int = 30) -> bool:
    for _ in range(tries):
        try:
            resp = await client.get(f"{BASE_URL}/api/tags")
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        print("[pull_models] 等待 Ollama 启动...", flush=True)
        await asyncio.sleep(2)
    return False


async def list_models(client: httpx.AsyncClient) -> set[str]:
    try:
        resp = await client.get(f"{BASE_URL}/api/tags")
        return {m.get("name", "") for m in resp.json().get("models", [])}
    except httpx.HTTPError:
        return set()


async def pull(client: httpx.AsyncClient, name: str) -> None:
    print(f"[pull_models] 拉取模型 {name} ...", flush=True)
    async with client.stream("POST", f"{BASE_URL}/api/pull", json={"name": name, "stream": True}) as resp:
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            status = data.get("status", "")
            if status:
                print(f"[pull_models] {name}: {status}", flush=True)


async def main() -> None:
    timeout = httpx.Timeout(connect=5.0, read=None, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if not await wait_ollama(client):
            print("[pull_models] 警告：Ollama 不可达，跳过模型拉取（AI 功能将在服务就绪后可用）", flush=True)
            return
        existing = await list_models(client)
        for model in (CHAT_MODEL, EMBED_MODEL):
            if any(m == model or m.startswith(model + ":") for m in existing):
                print(f"[pull_models] {model} 已存在，跳过", flush=True)
                continue
            try:
                await pull(client, model)
            except httpx.HTTPError as e:
                print(f"[pull_models] 拉取 {model} 失败: {e}", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
