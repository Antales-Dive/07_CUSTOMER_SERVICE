"""FastAPI entry point for the campus emotional companion."""

import hashlib
import hmac
import asyncio
import json
import secrets
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
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
    permanently_delete_deleted_session,
    delete_user_tokens,
    get_messages,
    get_or_create_anonymous_user,
    get_session,
    get_user_by_id,
    get_user_by_token,
    get_user_by_username,
    init_db,
    get_admin_session,
    list_admin_session_messages,
    list_admin_user_sessions,
    list_account_users,
    list_sessions,
    list_tickets,
    migrate_anonymous_sessions,
    reset_user_password,
    soft_delete_session,
    set_user_role,
    touch_session,
    update_user_password,
    update_session_title,
)
from models import (
    AdminAccountInfo,
    AdminMessageInfo,
    AdminRoleUpdate,
    AdminSessionDetail,
    AdminSessionInfo,
    AuthRequest,
    AuthResponse,
    ChangePasswordRequest,
    ChatRequest,
    ChatResponse,
    SessionDetail,
    SessionInfo,
    TicketCreate,
    TicketInfo,
)
from rag import build_faq_search_tool, build_vectorstore, load_faq_documents, should_use_knowledge_base
from safety import classify_input_rules, safe_fallback, scan_output_window, validate_output_rules


MCP_NPX_COMMAND = "npx.cmd" if sys.platform == "win32" else "npx"


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
        role=user.get("role", "user"),
        must_change_password=bool(user.get("must_change_password", 0)),
    )


async def _resolve_active_user(request: Request) -> dict:
    user = await _resolve_current_user(request)
    if user.get("mode") == "account" and user.get("must_change_password"):
        raise HTTPException(status_code=403, detail="请先修改密码后再继续使用")
    return user


async def _require_account_user(request: Request, *, allow_forced_change: bool = False) -> dict:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录账号")
    user = await _resolve_current_user(request)
    if user.get("mode") != "account":
        raise HTTPException(status_code=403, detail="该功能需要账号登录")
    if user.get("must_change_password") and not allow_forced_change:
        raise HTTPException(status_code=403, detail="请先修改密码后再继续使用")
    return user


async def _require_admin(request: Request) -> dict:
    user = await _require_account_user(request)
    if user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="没有管理员权限")
    return user


async def _require_super_admin(request: Request) -> dict:
    user = await _require_account_user(request)
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="只有总管可以管理管理员权限")
    return user


def _message_content(message: object) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _extract_agent_answer(response: object) -> str:
    if isinstance(response, dict):
        messages = response.get("messages", [])
        if messages:
            return _message_content(messages[-1]).strip()
    return ""


def _extract_stream_content(chunk: object) -> str:
    if isinstance(chunk, tuple) and chunk:
        return _message_content(chunk[0])
    if isinstance(chunk, dict):
        if isinstance(chunk.get("delta"), str):
            return chunk["delta"]
        if isinstance(chunk.get("content"), str):
            return chunk["content"]
        messages = chunk.get("messages")
        if messages:
            return _message_content(messages[-1])
        for value in chunk.values():
            text = _extract_stream_content(value)
            if text:
                return text
    return _message_content(chunk)


def sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _build_history(session_id: str) -> list[dict]:
    return [
        {"role": "user" if message["role"] == "user" else "assistant", "content": message["content"]}
        for message in await get_messages(DB_PATH, session_id)
    ]


def _rag_tool_for_request(content: str, mode: str):
    if mode == "companion" and should_use_knowledge_base(content):
        return app.state.faq_tool
    return None


async def _invoke_safe_answer(
    session_id: str, messages: list[dict], mode: str, content: str
) -> str:
    agent = await build_agent(
        session_id=session_id,
        mcp_tools=app.state.mcp_tools,
        rag_tool=_rag_tool_for_request(content, mode),
        mode=mode,
    )
    response = await agent.ainvoke({"messages": messages})
    answer = _extract_agent_answer(response)
    decision = validate_output_rules(answer)
    if decision.result == "rewrite":
        response = await agent.ainvoke(
            {
                "messages": messages
                + [
                    {"role": "assistant", "content": answer},
                    {
                        "role": "system",
                        "content": "请重写上一条回答，只保留安全、可执行、非诊断性的建议，控制在 400 tokens 内。",
                    },
                ]
            }
        )
        answer = _extract_agent_answer(response)
        decision = validate_output_rules(answer)
    if decision.result != "approved":
        return safe_fallback("caution")
    return answer


async def _complete_chat(session_id: str, session: dict, content: str, answer: str) -> None:
    await add_message(DB_PATH, session_id, "assistant", answer)
    if session["title"] == "新会话":
        await update_session_title(DB_PATH, session_id, content[:20])
    else:
        await touch_session(DB_PATH, session_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(DB_PATH)

    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            "filesystem": {
                "command": MCP_NPX_COMMAND,
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


@app.get("/admin")
async def admin_page():
    return FileResponse(f"{STATIC_DIR}/admin.html")


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
    user = await _resolve_active_user(request)
    session = await create_session(DB_PATH, user["id"])
    return SessionInfo(
        session_id=session["id"],
        title=session["title"],
        updated_at=session["created_at"],
        message_count=0,
    )


@app.get("/api/sessions", response_model=list[SessionInfo])
async def api_list_sessions(request: Request):
    user = await _resolve_active_user(request)
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
    user = await _resolve_active_user(request)
    session = await get_session(DB_PATH, user["id"], session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await get_messages(DB_PATH, session_id)
    return SessionDetail(session_id=session_id, title=session["title"], messages=messages)


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str, request: Request):
    user = await _resolve_active_user(request)
    if not await soft_delete_session(DB_PATH, user["id"], session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@app.post("/api/chat/{session_id}", response_model=ChatResponse)
async def api_chat(session_id: str, payload: ChatRequest, request: Request):
    user = await _resolve_active_user(request)
    session = await get_session(DB_PATH, user["id"], session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    content = payload.content
    await add_message(DB_PATH, session_id, "user", content)
    decision = classify_input_rules(content)
    if decision.level in {"urgent", "disallowed"}:
        answer = safe_fallback(decision.level)
    else:
        try:
            answer = await _invoke_safe_answer(
                session_id, await _build_history(session_id), payload.mode, content
            )
        except Exception:
            answer = "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。"

    await _complete_chat(session_id, session, content, answer)
    return ChatResponse(role="assistant", content=answer, session_id=session_id)


@app.post("/api/chat/{session_id}/stream")
async def api_chat_stream(session_id: str, payload: ChatRequest, request: Request):
    user = await _resolve_active_user(request)
    session = await get_session(DB_PATH, user["id"], session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    content = payload.content
    await add_message(DB_PATH, session_id, "user", content)
    messages = await _build_history(session_id)

    async def event_stream() -> AsyncIterator[str]:
        yield sse_event("start", {"session_id": session_id, "mode": payload.mode})
        decision = classify_input_rules(content)
        if decision.level in {"urgent", "disallowed"}:
            answer = safe_fallback(decision.level)
            yield sse_event("delta", {"text": answer})
            await _complete_chat(session_id, session, content, answer)
            yield sse_event("done", {"session_id": session_id})
            return

        answer_parts: list[str] = []
        rolling_window = ""
        try:
            agent = await build_agent(
                session_id=session_id,
                mcp_tools=app.state.mcp_tools,
                rag_tool=_rag_tool_for_request(content, payload.mode),
                mode=payload.mode,
            )
            if not hasattr(agent, "astream"):
                answer = await _invoke_safe_answer(session_id, messages, payload.mode, content)
                yield sse_event("delta", {"text": answer})
                await _complete_chat(session_id, session, content, answer)
                yield sse_event("done", {"session_id": session_id})
                return

            assembled = ""
            async for chunk in agent.astream({"messages": messages}):
                text = _extract_stream_content(chunk)
                if not text:
                    continue
                if assembled and text.startswith(assembled):
                    delta = text[len(assembled) :]
                    assembled = text
                else:
                    delta = text
                    assembled += delta
                if not delta:
                    continue
                rolling_window = (rolling_window + delta)[-1024:]
                if scan_output_window(rolling_window):
                    yield sse_event(
                        "error",
                        {"message": safe_fallback("caution"), "reason_code": "unsafe_output"},
                    )
                    return
                answer_parts.append(delta)
                yield sse_event("delta", {"text": delta})

            answer = "".join(answer_parts).strip()
            if validate_output_rules(answer).result != "approved":
                yield sse_event(
                    "error",
                    {"message": safe_fallback("caution"), "reason_code": "output_review_failed"},
                )
                return
            if not answer:
                answer = "我暂时没有生成有效回答，请换一种说法再试试。"
            await _complete_chat(session_id, session, content, answer)
            yield sse_event("done", {"session_id": session_id})
        except asyncio.CancelledError:
            raise
        except Exception:
            answer = "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。"
            yield sse_event("error", {"message": answer, "reason_code": "agent_unavailable"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/auth/change-password", response_model=AuthResponse)
async def api_change_password(payload: ChangePasswordRequest, request: Request):
    user = await _require_account_user(request, allow_forced_change=True)
    if not user.get("password_hash") or not verify_password(
        payload.old_password, user["password_hash"]
    ):
        raise HTTPException(status_code=400, detail="原密码错误")
    await update_user_password(DB_PATH, user["id"], hash_password(payload.new_password))
    await delete_user_tokens(DB_PATH, user["id"])
    updated_user = await get_user_by_id(DB_PATH, user["id"])
    return _auth_response(updated_user, await _issue_token(user["id"]))


@app.get("/api/admin/users", response_model=list[AdminAccountInfo])
async def api_admin_users(request: Request, query: str = ""):
    await _require_admin(request)
    return [
        AdminAccountInfo(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            must_change_password=bool(row["must_change_password"]),
        )
        for row in await list_account_users(DB_PATH, query)
    ]


@app.post("/api/admin/users/{user_id}/reset-password")
async def api_admin_reset_password(user_id: str, request: Request):
    await _require_admin(request)
    target = await get_user_by_id(DB_PATH, user_id)
    if not target or target.get("mode") != "account":
        raise HTTPException(status_code=404, detail="账号不存在")
    if target.get("role") != "user":
        raise HTTPException(status_code=403, detail="不能重置管理员密码")
    updated = await reset_user_password(DB_PATH, user_id, hash_password("123"))
    if not updated:
        raise HTTPException(status_code=409, detail="账号状态已变化，请刷新后重试")
    await delete_user_tokens(DB_PATH, user_id)
    return {"ok": True, "must_change_password": True}


@app.patch("/api/admin/users/{user_id}/role", response_model=AdminAccountInfo)
async def api_admin_role(user_id: str, payload: AdminRoleUpdate, request: Request):
    await _require_super_admin(request)
    target = await get_user_by_id(DB_PATH, user_id)
    if not target or target.get("mode") != "account":
        raise HTTPException(status_code=404, detail="账号不存在")
    if target.get("role") == "super_admin":
        raise HTTPException(status_code=403, detail="总管权限不可修改")
    updated = await set_user_role(DB_PATH, user_id, payload.role)
    if not updated:
        raise HTTPException(status_code=409, detail="账号状态已变化，请刷新后重试")
    return AdminAccountInfo(
        id=updated["id"],
        username=updated["username"],
        role=updated["role"],
        must_change_password=bool(updated["must_change_password"]),
    )


@app.get("/api/admin/users/{user_id}/sessions", response_model=list[AdminSessionInfo])
async def api_admin_user_sessions(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    await _require_super_admin(request)
    target = await get_user_by_id(DB_PATH, user_id)
    if not target or target.get("mode") != "account":
        raise HTTPException(status_code=404, detail="账号不存在")
    rows = await list_admin_user_sessions(DB_PATH, user_id, limit, offset)
    return [
        AdminSessionInfo(
            session_id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            message_count=row["message_count"],
            deleted_at=row["deleted_at"],
        )
        for row in rows
    ]


@app.get("/api/admin/sessions/{session_id}/messages", response_model=AdminSessionDetail)
async def api_admin_session_messages(session_id: str, request: Request):
    await _require_super_admin(request)
    session = await get_admin_session(DB_PATH, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await list_admin_session_messages(DB_PATH, session_id)
    return AdminSessionDetail(
        session_id=session_id,
        title=session["title"],
        username=session["username"],
        messages=[AdminMessageInfo(**message) for message in messages],
    )


@app.delete("/api/admin/sessions/{session_id}")
async def api_admin_delete_deleted_session(session_id: str, request: Request):
    await _require_super_admin(request)
    session = await get_admin_session(DB_PATH, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if not session.get("deleted_at"):
        raise HTTPException(status_code=409, detail="只能永久删除用户已删除的会话")
    if not await permanently_delete_deleted_session(DB_PATH, session_id):
        raise HTTPException(status_code=409, detail="会话状态已变化，请刷新后重试")
    return {"ok": True}


@app.get("/api/tickets", response_model=list[TicketInfo])
async def api_list_tickets(request: Request):
    user = await _resolve_active_user(request)
    rows = await list_tickets(DB_PATH, user["id"])
    return [TicketInfo(**row) for row in rows]


@app.post("/api/tickets", response_model=TicketInfo)
async def api_create_ticket(payload: TicketCreate, request: Request):
    user = await _resolve_active_user(request)
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
