"""轻量 Agent（§6.6）：基于 LLM function calling 的工具调用循环，不引入重型框架。

- 最多 MAX_TOOL_ROUNDS 轮工具调用，防止死循环
- 危险操作二次确认：首轮工具调用只返回确认提示（并在 Redis 登记待确认记录），
  由 LLM 向用户求确认；用户在后续消息中明确同意后，LLM 携带 confirm=true 重新调用，
  服务端校验待确认记录匹配后才真正执行
- 工具调用记录通过 done 事件返回，写入 chat_messages.tool_calls 审计
"""
import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis
from app.models import User
from app.services.ai import tools
from app.services.ai.llm import get_llm

logger = logging.getLogger(__name__)

# 工具调用最大轮数
MAX_TOOL_ROUNDS = 3

# 待确认操作的 Redis 键与有效期
_PENDING_KEY = "ai:agent:pending:{session_id}"
_PENDING_TTL_SECONDS = 15 * 60


async def run_agent(
    db: AsyncSession,
    user: User,
    session_id: uuid.UUID,
    system_prompt: str,
    history: list[dict],
    user_message: str,
):
    """Agent 主循环：流式生成 + 工具调用，产出事件流。

    事件格式：
      {"type": "tool", "name", "args", "status": "running"}
      {"type": "tool", "name", "status": "done", "result"}
      {"type": "delta", "content"}
      {"type": "done", "content", "tool_records"}
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # 存在待确认的危险操作：提示 LLM 依据用户最新回复决定是否携带 confirm 执行
    pending = await _load_pending(session_id)
    if pending is not None:
        messages.append(
            {
                "role": "system",
                "content": (
                    f"系统提示：你上一轮请求用户确认是否执行操作 {pending['tool']}"
                    f"（参数：{json.dumps(pending['args'], ensure_ascii=False)}）。"
                    "请根据用户最新回复判断：若用户明确同意，立即调用该工具并传入 confirm=true 与原参数；"
                    "若用户拒绝或态度不明，绝不传 confirm=true，并礼貌回应用户。"
                ),
            }
        )

    llm = get_llm()
    tool_records: list[dict] = []
    content = ""
    rounds_used = 0
    while True:
        # 达到轮数上限后不再提供工具定义，强制收敛为最终文本回复
        tool_defs = tools.TOOLS if rounds_used < MAX_TOOL_ROUNDS else None
        parts: list[str] = []
        calls: list[dict] = []
        async for chunk in llm.chat_stream(messages, tools=tool_defs, temperature=0.6):
            if chunk.get("delta"):
                parts.append(chunk["delta"])
                yield {"type": "delta", "content": chunk["delta"]}
            elif chunk.get("tool_calls"):
                calls = chunk["tool_calls"]
        content = "".join(parts).strip()
        if not calls or tool_defs is None:
            break

        messages.append({"role": "assistant", "content": content, "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            yield {"type": "tool", "name": name, "args": args, "status": "running"}
            result = await _execute_with_guard(db, user, session_id, name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            tool_records.append({"name": name, "args": args, "result": result})
            yield {"type": "tool", "name": name, "status": "done", "result": result}
        rounds_used += 1

    yield {"type": "done", "content": content, "tool_records": tool_records}


async def _execute_with_guard(
    db: AsyncSession, user: User, session_id: uuid.UUID, name: str, args: dict
) -> dict:
    """执行工具；危险工具附加二次确认守卫。

    - 未传 confirm：执行后若返回确认提示，则登记 Redis 待确认记录
    - 传了 confirm=true：必须存在同名的待确认记录才真正执行，防止模型绕过确认
    """
    if name not in tools.DANGEROUS_TOOLS:
        return await tools.execute_tool(db, user, name, args)

    if not args.get("confirm"):
        result = await tools.execute_tool(db, user, name, args)
        if result.get("need_confirm"):
            safe_args = {k: v for k, v in args.items() if k != "confirm"}
            await _save_pending(session_id, {"tool": name, "args": safe_args})
        return result

    pending = await _load_pending(session_id)
    if pending is None or pending.get("tool") != name:
        return {"success": False, "message": "未找到待确认的操作，请先征得用户确认后再执行"}
    result = await tools.execute_tool(db, user, name, args)
    await _clear_pending(session_id)
    return result


async def _load_pending(session_id: uuid.UUID) -> dict | None:
    try:
        raw = await redis.get(_PENDING_KEY.format(session_id=session_id))
        return json.loads(raw) if raw else None
    except Exception:
        logger.warning("读取待确认操作失败: session=%s", session_id)
        return None


async def _save_pending(session_id: uuid.UUID, data: dict) -> None:
    try:
        await redis.set(
            _PENDING_KEY.format(session_id=session_id),
            json.dumps(data, ensure_ascii=False),
            ex=_PENDING_TTL_SECONDS,
        )
    except Exception:
        logger.warning("登记待确认操作失败: session=%s", session_id)


async def _clear_pending(session_id: uuid.UUID) -> None:
    try:
        await redis.delete(_PENDING_KEY.format(session_id=session_id))
    except Exception:
        logger.warning("清除待确认操作失败: session=%s", session_id)
