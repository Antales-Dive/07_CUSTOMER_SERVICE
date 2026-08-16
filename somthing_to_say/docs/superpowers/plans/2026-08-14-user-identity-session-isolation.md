# 用户身份与会话隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为「有话说」增加匿名身份和账号密码两种可选模式，让每个用户只能读取自己的会话，并在打开历史会话时自动恢复完整上下文。

**Architecture:** 浏览器为匿名模式保存一个 UUID；账号模式通过登录接口取得随机认证令牌。服务端将两种身份统一解析为当前用户，并在所有会话读写 SQL 中增加用户过滤。注册成功时把当前匿名用户的会话迁移到新账号，登录已有账号时只加载该账号的会话。

**Tech Stack:** FastAPI、Pydantic、aiosqlite、SQLite、浏览器原生 JavaScript、Python 标准库 `hashlib`/`secrets`。

---

### Task 1: 为用户和认证数据建立数据库边界

**Files:**
- Modify: `database.py`
- Test: `tests/test_companion_backend.py`

- [ ] **Step 1: 写数据库行为测试**

覆盖以下行为：初始化后存在 `users` 表；匿名用户可幂等创建；用户名按规范化值唯一；密码只保存哈希字段；注册时可把匿名用户的会话迁移到账号；按用户列出、读取和创建会话。

- [ ] **Step 2: 运行测试确认缺少实现**

Run: `python -m unittest tests.test_companion_backend -v`

Expected: 新增用户隔离测试失败，现有测试保持通过。

- [ ] **Step 3: 实现最小数据库 API**

在 `database.py` 增加：

```python
async def get_or_create_anonymous_user(db_path: str, anonymous_id: str) -> dict: ...
async def create_account(db_path: str, username: str, password_hash: str) -> dict: ...
async def get_user_by_username(db_path: str, normalized_username: str) -> dict | None: ...
async def get_user_by_token(db_path: str, token_hash: str) -> dict | None: ...
async def create_auth_token(db_path: str, user_id: str, token_hash: str) -> None: ...
async def migrate_anonymous_sessions(db_path: str, anonymous_user_id: str, user_id: str) -> None: ...
async def create_session(db_path: str, user_id: str) -> dict: ...
async def list_sessions(db_path: str, user_id: str) -> list[dict]: ...
async def get_session(db_path: str, user_id: str, session_id: str) -> dict | None: ...
```

保留旧数据库可启动：通过 `CREATE TABLE IF NOT EXISTS` 和必要的 `ALTER TABLE` 迁移为已有 `sessions` 增加 `user_id`，旧会话归入一个稳定的 legacy 匿名用户，避免历史数据丢失。

- [ ] **Step 4: 运行数据库测试**

Run: `python -m unittest tests.test_companion_backend -v`

Expected: 用户、账号、会话隔离测试通过。

- [ ] **Step 5: 提交数据库边界**

```bash
git add database.py tests/test_companion_backend.py
git commit -m "feat: isolate sessions by user"
```

### Task 2: 增加认证模型和服务端身份解析

**Files:**
- Modify: `models.py`
- Modify: `main.py`
- Test: `tests/test_companion_backend.py`

- [ ] **Step 1: 写认证接口测试**

覆盖匿名身份、注册、重复用户名、密码长度、登录成功、错误密码、退出认证和跨用户会话访问返回 404/403 的行为。

- [ ] **Step 2: 实现标准库密码处理和令牌解析**

在 `main.py` 增加：

```python
def hash_password(password: str, salt: bytes | None = None) -> str: ...
def verify_password(password: str, stored: str) -> bool: ...
def normalize_username(username: str) -> str: ...
def resolve_current_user(request: Request) -> dict: ...
```

使用 `secrets.token_bytes` 生成盐和认证令牌，使用 `hashlib.pbkdf2_hmac` 哈希密码与令牌，并用 `hmac.compare_digest` 比较结果；不记录密码、令牌或其哈希。

- [ ] **Step 3: 增加认证 API**

增加 `POST /api/auth/anonymous`、`POST /api/auth/register`、`POST /api/auth/login` 和 `POST /api/auth/logout`。注册与登录响应返回当前用户模式、用户展示名和一次性返回的认证令牌；匿名模式返回匿名 ID。注册时迁移当前匿名会话。

- [ ] **Step 4: 将现有会话和聊天接口绑定当前用户**

为 `POST /api/sessions`、`GET /api/sessions`、`GET /api/sessions/{session_id}`、`POST /api/chat/{session_id}` 和遗留工单入口统一注入当前用户，并在数据库查询时传入 `user_id`。

- [ ] **Step 5: 运行后端测试**

Run: `python -m unittest tests.test_companion_backend -v`

Expected: 认证与会话隔离测试通过，旧安全边界测试继续通过。

- [ ] **Step 6: 提交后端认证**

```bash
git add main.py models.py database.py tests/test_companion_backend.py
git commit -m "feat: add anonymous and account auth"
```

### Task 3: 增加前端身份选择和上下文恢复

**Files:**
- Modify: `static/index.html`
- Test: `tests/test_companion_ui.py`

- [ ] **Step 1: 写前端结构测试**

断言页面存在匿名/账号选择、注册登录表单、退出按钮、认证令牌本地存储、认证请求头，以及打开会话时调用详情接口并渲染消息。

- [ ] **Step 2: 实现浏览器身份状态**

新增 `localStorage` 键：`youhua_anonymous_id`、`youhua_auth_token`、`youhua_auth_mode`。匿名模式首次访问生成 UUID；账号模式保存令牌但不保存密码。

- [ ] **Step 3: 实现认证面板和会话刷新**

在侧栏增加身份状态和“切换身份”入口。注册、登录、退出成功后刷新会话列表；注册成功继续使用当前匿名会话数据，登录已有账号切换到账号会话列表。

- [ ] **Step 4: 为 API 请求附加身份头**

所有会话和聊天请求附加 `X-Anonymous-Id` 或 `Authorization: Bearer <token>`，收到 401/403 时清理失效令牌并回到匿名模式。

- [ ] **Step 5: 保证点击历史会话自动恢复上下文**

`openSession(id)` 继续调用 `GET /api/sessions/{id}`，先清空当前消息，再按接口返回顺序渲染用户和助手消息；会话详情失败时保留当前页面并显示明确错误。

- [ ] **Step 6: 运行前端结构和脚本检查**

Run: `python -m unittest tests.test_companion_ui -v`

Run: 提取 `static/index.html` 内联脚本后执行 `node --check <temporary-file>`。

Expected: 前端结构测试和脚本语法检查通过。

- [ ] **Step 7: 提交前端认证体验**

```bash
git add static/index.html tests/test_companion_ui.py
git commit -m "feat: add selectable user identity modes"
```

### Task 4: 完整回归和真实页面验证

**Files:**
- Verify: `main.py`, `database.py`, `models.py`, `static/index.html`, `tests/`

- [ ] **Step 1: 运行完整测试**

Run: `python -m unittest discover -s tests -v`

Expected: 全部测试通过。

- [ ] **Step 2: 运行 Python 编译检查**

Run: `python -m compileall main.py config.py agent_factory.py database.py models.py rag.py`

Expected: 命令退出码为 0。

- [ ] **Step 3: 验证真实用户流程**

使用浏览器验证：匿名用户 A 创建会话并发送消息；匿名用户 B 看不到 A；A 注册后仍能看到原匿名会话；退出并登录已有账号后只能看到该账号会话；点击会话时消息上下文完整恢复；重复用户名和超过 10 位密码被拒绝。

- [ ] **Step 4: 检查变更边界**

Run: `git diff --check` and `git status --short`

确认不提交原有目录迁移状态、数据库文件、令牌、密码或 `.env` 内容。
