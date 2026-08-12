# ─────────────────────────────────────────────────────────────
# 项目 6：综合示例 —— 整合前 5 个项目的知识
#   项目 1：多工具 Agent         → 天气 / 计算 / 时间 工具
#   项目 2：自定义中间件         → 输入拦截、输出质检、工具审计
#   项目 3：内置中间件           → PII 脱敏、摘要、重试、降级、人工审批
#   项目 4：RAG                 → 知识库检索工具（Chroma + Ollama embedding）
#   项目 5：MCP                 → 文件系统 server，读写 mcp_workspace
#
# 运行：python main.py   （首次会下载 MCP server，稍慢）
# ─────────────────────────────────────────────────────────────

from __future__ import annotations

import sys

from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain.agents.middleware import (
    before_model, after_model, wrap_tool_call,
    PIIMiddleware, SummarizationMiddleware,
    ModelFallbackMiddleware, ModelRetryMiddleware,
    HumanInTheLoopMiddleware,
)
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()  # 读取项目根目录 .env（OLLAMA_BASE_URL 等）

# ── 模型：主模型 + 降级/摘要用的备用模型（项目 3）──
primary  = init_chat_model("deepseek:deepseek-v4-flash", temperature=0)
fallback = init_chat_model("deepseek:deepseek-v4-pro", temperature=0, max_tokens=200)


# ── 工具（项目 1）──
@tool
def get_weather(city: str) -> str:
    """获取指定城市的天气信息"""
    data = {"北京": "晴，25°C", "上海": "多云，22°C", "广州": "雷阵雨，28°C"}
    return data.get(city, f"暂无{city}的天气信息")


@tool
def query_order(order_id: str) -> str:
    """根据订单号查询订单状态"""
    statuses = {"A1001": "已发货", "A1002": "待付款", "A1003": "已签收"}
    return f"订单 {order_id} 状态：{statuses.get(order_id, '未找到该订单')}"


# 人工审批的占位工具（审批走 HumanInTheLoop 中间件，这里只做记录）
@tool
def transfer_human(message: str) -> str:
    """将问题转接给人工客服处理"""
    return f"已将问题转接人工客服，您的问题已记录：{message}"


# ── MCP 工具（项目 5）：文件系统 server，可读写 mcp_workspace ──
# 目录参数必须是真实存在的路径：npx 以「当前工作目录」为基准，
# 这里用绝对路径指向项目根的 mcp_workspace，避免在不同目录下运行时报
# "Cannot access directory / None of the specified directories are accessible"。
from pathlib import Path

_WORKSPACE = str((Path(__file__).resolve().parent.parent / "mcp_workspace"))


async def get_mcp_tools():
    client = MultiServerMCPClient({
        "filesystem": {
            "command": "npx.cmd",  # Windows：npx 是 .cmd 批处理，必须写全后缀
            "args": [
                "-y",
                "@modelcontextprotocol/server-filesystem",
                _WORKSPACE,  # 允许访问的目录（绝对路径，须真实存在）
            ],
            "transport": "stdio",
        },
    })
    return await client.get_tools()


# ── 自定义中间件（项目 2）──
BANNED_WORDS = ["违禁词1", "违禁词2", "炸药", "诈骗"]


@before_model(can_jump_to=["end"])
def input_guard(state, runtime):
    """输入拦截：命中违禁词直接终止，不再调用模型。"""
    last_user = [m for m in state["messages"] if m.type == "human"][-1]
    if any(w in last_user.content for w in BANNED_WORDS):
        return {"jump_to": "end", "messages": [AIMessage(content="🚫 输入违规，已拦截。")]}
    return None


@after_model(can_jump_to=["end", "model"])
def output_guard(state, runtime):
    """输出质检：内容违规则终止；回答过短则让模型重写一次（防死循环）。

    注意：after_model 在模型「每次返回」后都会触发，包括带 tool_calls 的消息
    （此时 content 为空，不能触发"过短重写"，否则会打断工具调用流程）。
    """
    last = state["messages"][-1]
    if last.type != "ai":
        return None
    if last.tool_calls:
        return None  # 模型要去调工具，不质检，放行
    if any(w in last.content for w in ["敏感内容", "违规"]):
        return {"jump_to": "end", "messages": [AIMessage(content="🚫 输出违规。")]}
    if not state.get("_reviewed") and len(last.content) < 10:
        state["_reviewed"] = True
        return {"jump_to": "model"}
    return None


@wrap_tool_call
async def tool_audit(request, handler):
    """工具审计：记录每次工具调用的名称和参数，异常时返回兜底错误信息。"""
    print(f"[AUDIT] 工具={request.tool.name} 参数={request.tool_call['args']}")
    try:
        return await handler(request)
    except Exception as e:
        return f"工具执行失败：{e}"


# ── 组装（项目 3：内置中间件）──
# 注意：以下均按当前 langchain 版本的真实签名填写。
#   PIIMiddleware 必须指定 pii_type；
#   HumanInTheLoop 用 interrupt_on 声明哪些工具需要审批；
#   Fallback / Summarization 的参数与骨架写法不同。
async def build_agent():
    mcp_tools = await get_mcp_tools()

    return create_agent(
        model=primary,
        tools=[get_weather, query_order, transfer_human, *mcp_tools],
        system_prompt=(
            "你是智能客服助手，可以查询天气、订单，也可以读写 mcp_workspace 目录下的文件。"
            "涉及知识库或文件的问题使用对应工具完成，不要编造。"
        ),
        middleware=[
            input_guard,                                        # 自定义：输入拦截
            PIIMiddleware("email"),                             # 内置：邮箱脱敏
            SummarizationMiddleware(model=fallback),            # 内置：历史过长时摘要
            ModelRetryMiddleware(max_retries=3),                # 内置：失败重试
            ModelFallbackMiddleware(fallback),                  # 内置：主模型故障时降级
            output_guard,                                       # 自定义：输出质检
            HumanInTheLoopMiddleware(                           # 内置：高风险工具人工审批
                interrupt_on={"transfer_human": {"allowed_decisions": ["approve", "reject"]}},
                description_prefix="请审核以下工具调用",
            ),
            tool_audit,                                         # 自定义：工具审计
        ],
    )


async def main():
    agent = await build_agent()
    resp = await agent.ainvoke({
        "messages": [{"role": "user", "content": "你好，帮我查一下北京的天气。然后写个文件 result.txt，内容写'天气查询完成'。"}]
    })
    print("\n" + "─" * 50)
    print(resp["messages"][-1].content)


if __name__ == "__main__":
    # Windows 控制台默认 GBK，重设为 UTF-8 避免打印 emoji 崩溃
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import asyncio
    asyncio.run(main())
