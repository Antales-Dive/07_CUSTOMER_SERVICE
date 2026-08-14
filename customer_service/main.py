"""FastAPI entry point for the campus emotional companion."""

import hashlib
import hmac
import secrets
import sys
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_factory import build_agent
from config import DB_PATH, MCP_WORKSPACE, STATIC_DIR
from database import (
    add_message,
    create_account,
    create_auth_token,
    create_session,
    create_ticket,
    delete_auth_token,
    get_messages,
    get_or_create_anonymous_user,
    get_session,
    get_user_by_token,
    get_user_by_username,
    init_db,
    list_sessions,
    list_tickets,
    migrate_anonymous_sessions,
    touch_session,
    update_session_title,
)
from models import (
    AuthRequest,
    AuthResponse,
    ChatRequest,
    ChatResponse,
    SessionDetail,
    SessionInfo,
    TicketCreate,
    TicketInfo,
)
from rag import build_faq_search_tool, build_vectorstore, load_faq_documents


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

_PASSWORD_ITERATIONS = 210_000


def _normalize_mcp_tool_schemas(tools: list) -> list:
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


def normalize_username(username: str) -> tuple[str, str]:
    display_name = username.strip()
    return display_name, display_name.casefold()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return f"pbkdf2_sha256${_PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _resolve_current_user(request: Request) -> dict:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        user = await get_user_by_token(DB_PATH, hash_token(token)) if token else None
        if not user:
            raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
        return user

    anonymous_id = request.headers.get("x-anonymous-id", "").strip()
    if not anonymous_id:
        raise HTTPException(status_code=400, detail="缺少用户身份信息")
    try:
        return await get_or_create_anonymous_user(DB_PATH, anonymous_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


async def _issue_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    await create_auth_token(DB_PATH, user_id, hash_token(token))
    return token


def _auth_response(user: dict, token: str | None = None) -> AuthResponse:
    return AuthResponse(
        mode=user["mode"],
        user_id=user["id"],
        username=user.get("username"),
        anonymous_id=user.get("anonymous_id"),
        token=token,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(DB_PATH)

    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            "filesystem": {
                "command": "npx.cmd",
                "args": ["-y", "@modelcontextprotocol/server-filesystem@0.6.0", MCP_WORKSPACE],
                "transport": "stdio",
            },
        }
    )
    app.state.mcp_tools = _normalize_mcp_tool_schemas(await client.get_tools())
    print(f"[启动] 已加载 {len(app.state.mcp_tools)} 个 MCP 工具")

    docs = load_faq_documents()
    vectorstore = build_vectorstore(docs)
    app.state.faq_tool = build_faq_search_tool(vectorstore)
    print("[启动] FAQ 知识库就绪")

    yield


app = FastAPI(title="有话说", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(f"{STATIC_DIR}/index.html")


@app.post("/api/auth/anonymous", response_model=AuthResponse)
async def api_anonymous(request: Request):
    anonymous_id = request.headers.get("x-anonymous-id", "").strip() or str(uuid.uuid4())
    user = await get_or_create_anonymous_user(DB_PATH, anonymous_id)
    return _auth_response(user)


@app.post("/api/auth/register", response_model=AuthResponse)
async def api_register(payload: AuthRequest, request: Request):
    anonymous_id = request.headers.get("x-anonymous-id", "").strip()
    if not anonymous_id:
        raise HTTPException(status_code=400, detail="注册前需要匿名身份")
    display_name, normalized = normalize_username(payload.username)
    if not normalized:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if await get_user_by_username(DB_PATH, normalized):
        raise HTTPException(status_code=409, detail="用户名已存在")

    anonymous_user = await get_or_create_anonymous_user(DB_PATH, anonymous_id)
    try:
        user = await create_account(
            DB_PATH,
            display_name,
            normalized,
            hash_password(payload.password),
        )
    except ValueError:
        raise HTTPException(status_code=409, detail="用户名已存在") from None
    await migrate_anonymous_sessions(DB_PATH, anonymous_user["id"], user["id"])
    return _auth_response(user, await _issue_token(user["id"]))


@app.post("/api/auth/login", response_model=AuthResponse)
async def api_login(payload: AuthRequest):
    _, normalized = normalize_username(payload.username)
    user = await get_user_by_username(DB_PATH, normalized)
    if not user or not user.get("password_hash") or not verify_password(
        payload.password, user["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _auth_response(user, await _issue_token(user["id"]))


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            await delete_auth_token(DB_PATH, hash_token(token))
    return {"ok": True}


@app.post("/api/sessions", response_model=SessionInfo)
async def api_create_session(request: Request):
    user = await _resolve_current_user(request)
    session = await create_session(DB_PATH, user["id"])
    return SessionInfo(
        session_id=session["id"],
        title=session["title"],
        updated_at=session["created_at"],
        message_count=0,
    )


@app.get("/api/sessions", response_model=list[SessionInfo])
async def api_list_sessions(request: Request):
    user = await _resolve_current_user(request)
    rows = await list_sessions(DB_PATH, user["id"])
    return [
        SessionInfo(
            session_id=row["id"],
            title=row["title"],
            updated_at=row["updated_at"],
            message_count=row["message_count"],
        )
        for row in rows
    ]


@app.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def api_get_session(session_id: str, request: Request):
    user = await _resolve_current_user(request)
    session = await get_session(DB_PATH, user["id"], session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await get_messages(DB_PATH, session_id)
    return SessionDetail(session_id=session_id, title=session["title"], messages=messages)


@app.post("/api/chat/{session_id}", response_model=ChatResponse)
async def api_chat(session_id: str, payload: ChatRequest, request: Request):
    user = await _resolve_current_user(request)
    session = await get_session(DB_PATH, user["id"], session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    content = payload.content
    await add_message(DB_PATH, session_id, "user", content)
    history = await get_messages(DB_PATH, session_id)
    messages = [
        {"role": "user" if message["role"] == "user" else "assistant", "content": message["content"]}
        for message in history
    ]

    agent = await build_agent(
        session_id=session_id,
        mcp_tools=app.state.mcp_tools,
        rag_tool=app.state.faq_tool,
    )
    try:
        response = await agent.ainvoke({"messages": messages})
        answer = response["messages"][-1].content
    except Exception as error:
        print(f"[ERROR] Agent 调用失败：{error}")
        answer = "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。"

    await add_message(DB_PATH, session_id, "assistant", answer)
    if session["title"] == "新会话":
        await update_session_title(DB_PATH, session_id, content[:20])
    else:
        await touch_session(DB_PATH, session_id)
    return ChatResponse(role="assistant", content=answer, session_id=session_id)


@app.get("/api/tickets", response_model=list[TicketInfo])
async def api_list_tickets(request: Request):
    user = await _resolve_current_user(request)
    rows = await list_tickets(DB_PATH, user["id"])
    return [TicketInfo(**row) for row in rows]


@app.post("/api/tickets", response_model=TicketInfo)
async def api_create_ticket(payload: TicketCreate, request: Request):
    user = await _resolve_current_user(request)
    session = await get_session(DB_PATH, user["id"], payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    ticket = await create_ticket(DB_PATH, payload.session_id, payload.user_message, payload.priority)
    return TicketInfo(**ticket)


if __name__ == "__main__":
    import asyncio
    import uvicorn

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    async def _start():
        server_config = uvicorn.Config(app, host="127.0.0.1", port=8000)
        server = uvicorn.Server(server_config)
        await server.serve()

    asyncio.run(_start())
