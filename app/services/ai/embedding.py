"""文本向量化入口。"""
from app.services.ai.llm import get_llm


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    return await get_llm().embed(texts)


async def get_embedding(text: str) -> list[float]:
    return (await get_embeddings([text]))[0]
