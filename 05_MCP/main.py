# ─────────────────────────────────────────────────────────────
# LangChain 1.x MCP Agent 示例
# 通过 MCP（Model Context Protocol）把外部工具接入 Agent，
# 本例用文件系统 server 演示「读写文件」能力。
#
# 依赖：langchain, langchain-mcp-adapters, mcp(1.x)
# 运行：python perf.py
# ─────────────────────────────────────────────────────────────

import asyncio
# 标准库 sys：访问解释器相关对象（此处用 sys.stdout 调整输出编码）
import sys
from langchain.agents import create_agent          # 创建 Agent 的入口
from langchain.chat_models import init_chat_model  # 按字符串初始化聊天模型
from langchain_mcp_adapters.client import MultiServerMCPClient  # 多 server MCP 客户端
from langchain.agents.middleware import wrap_tool_call          # 工具调用中间件装饰器


# ── 1. 配置 MCP Server（以文件系统 + 搜索为例）──
# 字典键是 server 名字，值是启动参数；可自由追加更多 server（数据库、搜索等）。
mcp_config = {
    "filesystem": {
        "command": "npx.cmd",  # Windows 上 npx 是 .cmd 批处理，create_subprocess_exec 需显式指定
        "args": [
            "-y",  # -y：跳过 npx 的安装确认
            "@modelcontextprotocol/server-filesystem",  # MCP 官方文件系统 server
            "mcp_workspace",  # 允许该 server 访问的目录（必须是真实存在的路径）
        ],
        "transport": "stdio",  # 传输方式：stdio（标准输入输出）；也可用 sse/http
    },
    # 可以加更多 server，如数据库、搜索引擎等
}


# ── 2. 自定义中间件：工具调用日志 ──
# @wrap_tool_call 把下面的函数转换成 Agent 中间件，在每次工具调用前后插入钩子。
# 注意：agent 用 ainvoke（异步）时，此处函数必须是 async 版本。
@wrap_tool_call
async def tool_logger(request, handler):
    """在工具调用前后打印日志。

    参数:
        request: ToolCallRequest 对象，包含本次调用信息：
                 - tool: 被调用的 BaseTool 实例（用 .name 取工具名）
                 - tool_call: dict，含 name / args / id（args 是参数字典）
        handler: 下一个处理器，调用 handler(request) 才真正执行工具；
                 不调用则工具不会执行（可用于拦截/放行）。
    返回:
        工具执行结果（ToolMessage），原样透传给 Agent。
    """
    # 执行前打日志：工具名 + 参数
    print(f"🔧 即将调用工具：{request.tool.name}，参数：{request.tool_call['args']}")
    result = await handler(request)  # await 真正执行工具调用
    # 执行后打日志：只截取前 200 字符，避免超长输出刷屏
    print(f"✅ 工具返回：{str(result)[:200]}")
    return result


# ── 3. 异步主函数 ──
async def main():
    """构建 Agent 并执行一次「创建文件」任务。

    参数:
        无
    返回:
        None；最终回答直接 print 到控制台。
    """
    # 创建 MCP 客户端（注意：旧版用 async with 作为上下文管理器，
    # 新版本已改为手动调用方法，不支持 async with，会抛 NotImplementedError）
    client = MultiServerMCPClient(mcp_config)

    # 从所有 MCP Server 加载工具（get_tools 自动聚合所有 server 的工具）
    mcp_tools = await client.get_tools()

    # 初始化聊天模型；'provider:model' 格式指定模型源
    model = init_chat_model("deepseek:deepseek-v4-flash", temperature=0)

    # 组装 Agent：模型 + 工具 + 系统提示词 + 中间件
    agent = create_agent(
        model=model,
        tools=mcp_tools,
        system_prompt="你可以读写项目 mcp_workspace 目录下的文件，帮用户管理文件。",
        middleware=[tool_logger],
    )

    # 调用 Agent：输入必须是 {"messages": [...]} 结构，模拟一次用户对话
    resp = await agent.ainvoke({
        "messages": [{"role": "user", "content": "在 mcp_workspace 下创建一个 hello.txt，内容写 'Hello LangChain 1.x'"}]
    })
    # resp["messages"][-1] 是最后一条消息，即 Agent 的最终回答
    print(resp["messages"][-1].content)


if __name__ == "__main__":
    # 仅在「直接运行本文件」时执行；被 import 时跳过（__name__ 不是 "__main__"）。
    # Windows 控制台默认 GBK，重设为 UTF-8 避免打印 emoji 时崩溃
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 用户按 Ctrl+C：优雅退出，不打印 traceback
        print("\n⏹ 已中断（Ctrl+C）")
