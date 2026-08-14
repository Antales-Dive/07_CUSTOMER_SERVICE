"""FastAPI 应用入口：路由定义 + lifespan 管理。

- lifespan：启动时初始化数据库、加载 MCP 工具和 FAQ 检索工具（各一次）
- chat 路由：会话、消息和遗留工单路由
"""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_factory import build_agent
from config import DB_PATH, MCP_WORKSPACE, STATIC_DIR
from database import (#数据库
    add_message,
    create_session,
    create_ticket,
    get_messages,
    get_session,
    init_db,
    list_sessions,
    list_tickets,
    touch_session,
    update_session_title,
)
from models import ChatRequest, ChatResponse, SessionDetail, SessionInfo, TicketCreate, TicketInfo
from rag import build_faq_search_tool, build_vectorstore, load_faq_documents


# ── MCP 工具 schema 修复 ──
# @modelcontextprotocol/server-filesystem@0.6.0 存在 zod→JSON Schema 转换 bug：
# read_file 等工具上报的 inputSchema 只有 {"$schema": ...}，缺少 type/properties，
# DeepSeek 会直接拒绝这类函数（要求 function 参数必须是 type: "object" 的 JSON Schema）。
# 这里按该服务器源码（z.object 定义）补齐正确的输入 schema。

_FILESYSTEM_TOOL_SCHEMAS: dict[str, dict] = {
    "read_file": {"path": {"type": "string"}},
    "read_multiple_files": {"paths": {"type": "array", "items": {"type": "string"}}},
    "write_file": {"path": {"type": "string"}, "content": {"type": "string"}},
    "create_directory": {"path": {"type": "string"}},
    "list_directory": {"path": {"type": "string"}},
    "move_file": {"source": {"type": "string"}, "destination": {"type": "string"}},
    "search_files": {"path": {"type": "string"}, "pattern": {"type": "string"}},
    "get_file_info": {"path": {"type": "string"}},
}


def _normalize_mcp_tool_schemas(tools: list) -> list:
    """补齐 MCP 工具的输入 schema（type/properties），避免被模型 API 拒绝。

    仅处理「args_schema 是 dict 且缺 type/properties」的坏 schema；
    已正常的工具（如 list_allowed_directories）保持不变。
    """
    for tool in tools:
        schema = getattr(tool, "args_schema", None)
        if isinstance(schema, dict) and (
            schema.get("type") != "object" or "properties" not in schema
        ):
            props = _FILESYSTEM_TOOL_SCHEMAS.get(tool.name, {})
            tool.args_schema = {
                "type": "object",
                "properties": props,
                "required": list(props.keys()),
            }
    return tools


# ── lifespan：启动时一次性加载的共享资源 ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 数据库
    await init_db(DB_PATH)

    # MCP 文件系统工具（异步加载，14 个文件操作工具）
    from langchain_mcp_adapters.client import MultiServerMCPClient
    client = MultiServerMCPClient({
        "filesystem": {
            "command": "npx.cmd",
            "args": ["-y", "@modelcontextprotocol/server-filesystem@0.6.0", MCP_WORKSPACE],
            "transport": "stdio",
        },
    })
    app.state.mcp_tools = _normalize_mcp_tool_schemas(await client.get_tools())
    print(f"[启动] 已加载 {len(app.state.mcp_tools)} 个 MCP 工具")

    # FAQ 知识库（复用已持久化向量库，避免重复 embedding）
    docs = load_faq_documents()
    vectorstore = build_vectorstore(docs)
    app.state.faq_tool = build_faq_search_tool(vectorstore)
    print("[启动] FAQ 知识库就绪（检索带置信度阈值，无答案时提供官方帮助入口）")

    yield

    # 关闭时（如有需要，清理资源）


app = FastAPI(title="有话说", lifespan=lifespan)

# 静态文件（前端页面）
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(f"{STATIC_DIR}/index.html")


# ── 会话路由 ──

@app.post("/api/sessions", response_model=SessionInfo)
async def api_create_session():
    s = await create_session(DB_PATH)
    return SessionInfo(
        session_id=s["id"], title=s["title"], updated_at=s["created_at"], message_count=0
    )


@app.get("/api/sessions", response_model=list[SessionInfo])
async def api_list_sessions():
    rows = await list_sessions(DB_PATH)
    return [
        SessionInfo(
            session_id=r["id"], title=r["title"], updated_at=r["updated_at"],
            message_count=r["message_count"],
        )
        for r in rows
    ]


@app.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def api_get_session(session_id: str):
    s = await get_session(DB_PATH, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = await get_messages(DB_PATH, session_id)
    return SessionDetail(session_id=session_id, title=s["title"], messages=msgs)


# ── 对话路由（核心）──

@app.post("/api/chat/{session_id}", response_model=ChatResponse)
async def api_chat(session_id: str, request: ChatRequest):
    s = await get_session(DB_PATH, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")

    content = request.content

    # 1. 保存用户消息
    await add_message(DB_PATH, session_id, "user", content)

    # 2. 重建对话历史（LangChain 格式）
    history = await get_messages(DB_PATH, session_id)
    messages = [
        {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
        for m in history
    ]

    # 3. 构建 Agent（绑定当前会话，闭包注入 session_id）
    agent = await build_agent(
        session_id=session_id,
        mcp_tools=app.state.mcp_tools,
        rag_tool=app.state.faq_tool,
    )

    # 4. 调用 Agent
    try:
        resp = await agent.ainvoke({"messages": messages})
        answer = resp["messages"][-1].content
    except Exception as e:
        print(f"[ERROR] Agent 调用失败：{e}")
        answer = "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。"

    # 5. 保存 AI 回复
    await add_message(DB_PATH, session_id, "assistant", answer)

    # 6. 更新会话（标题 + 活跃时间）
    if s["title"] == "新会话":
        await update_session_title(DB_PATH, session_id, content[:20])
    else:
        await touch_session(DB_PATH, session_id)

    return ChatResponse(role="assistant", content=answer, session_id=session_id)


# ── 工单路由 ──

@app.get("/api/tickets", response_model=list[TicketInfo])
async def api_list_tickets():
    rows = await list_tickets(DB_PATH)
    return [TicketInfo(**r) for r in rows]


@app.post("/api/tickets", response_model=TicketInfo)
async def api_create_ticket(request: TicketCreate):
    s = await get_session(DB_PATH, request.session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    t = await create_ticket(DB_PATH, request.session_id, request.user_message, request.priority)
    return TicketInfo(**t)


# 直接运行支持：python main.py
if __name__ == "__main__":
    import asyncio
    import uvicorn

    # Windows 控制台默认 GBK，重设为 UTF-8 避免打印 emoji 崩溃
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    async def _start():
        server_config = uvicorn.Config(app, host="127.0.0.1", port=8000)
        server = uvicorn.Server(server_config)
        await server.serve()

    asyncio.run(_start())
