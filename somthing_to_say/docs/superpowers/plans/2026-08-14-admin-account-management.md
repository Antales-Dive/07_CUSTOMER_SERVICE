# 管理员账号管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有账号“十里”升级为唯一总管，并增加分角色的管理员账号搜索、密码重置、角色管理、强制改密、用户软删除会话和总管只读查看/永久删除已标记会话的流程。

**Architecture:** 在现有 `users` 表增加 `role` 与 `must_change_password`，在 `sessions` 表增加用户软删除状态和删除时间。数据库初始化按规范化用户名幂等提升“十里”为 `super_admin`。普通管理员 API 只返回账号身份字段；总管通过独立的只读会话和消息接口查看指定用户数据，后端再次校验指定用户与会话归属。普通用户删除会话只做软删除，总管只能永久删除已软删除会话。聊天 API 继续按用户隔离。普通账号和管理员共用登录令牌，但强制改密状态只允许改密和退出。

**Tech Stack:** FastAPI、Pydantic、aiosqlite、SQLite、Python 标准库 PBKDF2、原生 HTML/CSS/JavaScript。

---

### Task 1: 扩展用户角色和改密状态

**Files:**
- Modify: `database.py`
- Test: `tests/test_admin_backend.py`

- [ ] **Step 1: 写迁移和权限数据测试**

测试临时 SQLite 数据库：初始化后用户有 `role` 和 `must_change_password`；规范化用户名“十里”被提升为唯一 `super_admin`；不存在“十里”时不创建默认账号；重复初始化不改变角色结果。

- [ ] **Step 2: 运行失败测试**

Run: `python -m unittest tests.test_admin_backend.UserRoleDatabaseTests -v`

Expected: 新增字段和角色迁移断言失败，现有用户隔离测试保持通过。

- [ ] **Step 3: 增加数据库字段和查询函数**

在 `users` 表加入 `role TEXT NOT NULL DEFAULT 'user'` 和 `must_change_password INTEGER NOT NULL DEFAULT 0`。已有数据库通过 `PRAGMA table_info(users)` 检测后执行 `ALTER TABLE`。实现以下明确函数：

```python
async def get_user_by_id(db_path: str, user_id: str) -> dict | None: ...
async def list_account_users(db_path: str, query: str) -> list[dict]: ...
async def set_user_role(db_path: str, user_id: str, role: str) -> dict | None: ...
async def reset_user_password(db_path: str, user_id: str, password_hash: str) -> bool: ...
async def update_user_password(db_path: str, user_id: str, password_hash: str) -> bool: ...
async def set_super_admin_by_username(db_path: str, normalized_username: str) -> dict | None: ...
async def delete_user_tokens(db_path: str, user_id: str) -> None: ...
```

创建唯一部分索引保证最多一个 `super_admin`。`list_account_users` 只选择 `id`、`username`、`role`、`must_change_password`，不查询密码哈希、令牌、匿名 ID、会话或消息。

- [ ] **Step 4: 运行数据库测试**

Run: `python -m unittest tests.test_admin_backend.UserRoleDatabaseTests -v`

Expected: 迁移、唯一总管和账号字段隔离测试通过。

- [ ] **Step 5: 提交数据库边界**

```bash
git add database.py tests/test_admin_backend.py
git commit -m "feat: add account roles and password state"
```

### Task 2: 实现改密和管理员 API 权限

**Files:**
- Modify: `models.py`
- Modify: `main.py`
- Test: `tests/test_admin_backend.py`

- [ ] **Step 1: 写认证和权限矩阵测试**

覆盖：普通用户修改密码必须提供原密码；重置后密码为 `123` 的哈希且 `must_change_password` 为真；旧令牌失效；管理员只能搜索和重置普通用户；总管可以授予/撤销 `admin`；普通管理员不能修改管理员或总管；普通管理员接口不返回会话/消息字段；总管可分页读取指定用户会话和完整消息，不能读取其他用户会话；用户名或会话不存在返回 404。

- [ ] **Step 2: 扩展响应与请求模型**

在 `models.py` 增加：

```python
class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=10)
    new_password: str = Field(..., min_length=1, max_length=10)

class AdminRoleUpdate(BaseModel):
    role: Literal["user", "admin"]
```

在 `AuthResponse` 增加 `role` 和 `must_change_password`；不增加密码、哈希或令牌以外的敏感字段。

- [ ] **Step 3: 实现统一管理员鉴权**

在 `main.py` 增加 `require_account_user`、`require_admin` 和 `require_super_admin`，统一检查 Bearer 令牌、用户角色和 `must_change_password`。账号管理 API 只使用 `list_account_users`；总管会话和消息接口使用独立的数据查询函数，并校验指定用户与会话归属。

- [ ] **Step 4: 实现改密接口**

增加 `POST /api/auth/change-password`：验证原密码，哈希新密码，删除旧令牌，签发新令牌并清除强制改密标志。增加重置接口：`POST /api/admin/users/{user_id}/reset-password`，固定把 `123` 哈希后保存并删除目标用户全部令牌。

- [ ] **Step 5: 实现管理员账号接口**

增加：

```text
GET   /api/admin/users?query=
PATCH /api/admin/users/{user_id}/role
GET   /api/admin/users/{user_id}/sessions?limit=&offset=
GET   /api/admin/sessions/{session_id}/messages
DELETE /api/sessions/{session_id}
DELETE /api/admin/sessions/{session_id}
```

角色接口只允许总管将普通账号设为 `user` 或 `admin`，不能操作总管。管理员搜索只返回允许字段；普通用户删除接口只执行软删除；总管永久删除接口只允许删除已被用户标记的会话，不能编辑或导出。

- [ ] **Step 6: 运行后端权限测试**

Run: `python -m unittest tests.test_admin_backend tests.test_user_isolation -v`

Expected: 权限矩阵、强制改密和原有会话隔离全部通过。

- [ ] **Step 7: 提交认证和管理员 API**

```bash
git add main.py models.py database.py tests/test_admin_backend.py
git commit -m "feat: add admin account controls"
```

### Task 3: 增加管理员页面

**Files:**
- Create: `static/admin.html`
- Modify: `main.py`
- Test: `tests/test_admin_ui.py`

- [ ] **Step 1: 写页面结构测试**

断言 `/admin` 页面包含用户名搜索、账号角色、强制改密状态、重置密码按钮、总管角色选择、返回聊天和退出入口；页面包含总管用户详情、会话和消息区域，但普通管理员运行时不显示详情入口；页面源码不包含普通聊天接口。

- [ ] **Step 2: 增加受保护的静态入口**

在 `main.py` 增加 `GET /admin`，只返回静态页面；实际数据接口仍由后端权限控制，不能把隐藏 URL 当作授权。

- [ ] **Step 3: 实现管理员查询和操作界面**

`admin.html` 从 `localStorage` 读取现有认证令牌，调用管理员 API。搜索结果只显示用户名、角色和改密状态。重置密码使用原生确认对话框，明确提示密码将变为 `123`；总管角色选择只显示 `user`/`admin`，隐藏总管自身操作。总管点击用户名后加载该用户会话列表，再点击会话加载完整消息；这些区域保持只读，不提供编辑、删除或导出按钮。

- [ ] **Step 4: 运行页面测试和脚本检查**

Run: `python -m unittest tests.test_admin_ui -v`

Run: 提取 `admin.html` 内联脚本后执行 `node --check <temporary-file>`。

Expected: 页面结构通过，脚本语法无错误，普通管理员无详情入口，总管会话和消息入口与只读约束存在。

- [ ] **Step 5: 提交管理员页面**

```bash
git add static/admin.html main.py tests/test_admin_ui.py
git commit -m "feat: add restricted admin page"
```

### Task 4: 在聊天页增加改密和强制改密流程

**Files:**
- Modify: `static/index.html`
- Test: `tests/test_companion_ui.py`

- [ ] **Step 1: 写前端改密测试**

断言账号面板存在原密码、新密码字段和修改按钮；管理员角色显示管理页面入口；`must_change_password` 状态打开改密面板；强制改密状态下不调用创建会话、读取会话或聊天接口。

- [ ] **Step 2: 实现账号状态展示**

保存 `role` 和 `must_change_password` 到当前页面状态，不保存密码。登录响应包含强制改密状态时，打开改密对话框并禁用聊天相关操作。

- [ ] **Step 3: 实现主动修改和强制修改**

提交原密码和新密码到 `/api/auth/change-password`，成功后保存新令牌、更新用户状态、关闭弹窗并恢复会话访问。用户名输入框不提供编辑入口。

- [ ] **Step 4: 运行前端测试**

Run: `python -m unittest tests.test_companion_ui -v`

Expected: 身份选择、上下文恢复、改密和强制改密测试全部通过。

- [ ] **Step 5: 提交聊天页改密流程**

```bash
git add static/index.html tests/test_companion_ui.py
git commit -m "feat: add password change flow"
```

### Task 5: 管理员真实页面回归

**Files:**
- Verify: `main.py`, `database.py`, `models.py`, `static/admin.html`, `static/index.html`, `tests/`

- [ ] **Step 1: 启动本地服务并检查入口**

Run: `python main.py`

验证 `/` 返回聊天页，`/admin` 返回管理员页，未登录访问管理员 API 返回 401，普通账号访问返回 403。

- [ ] **Step 2: 验证“十里”总管流程**

使用现有“十里”账号登录，搜索账号、授予普通账号管理员权限、撤销权限；确认总管自身不出现在可修改角色的目标操作中。

- [ ] **Step 3: 验证普通管理员流程**

普通管理员只搜索用户名和重置普通用户密码；确认页面没有会话/消息请求，不能查看对话，不能删除数据，不能操作管理员和总管。

- [ ] **Step 4: 验证总管只读查看流程**

总管点击普通用户名后能看到该用户的会话列表，点击会话后能看到完整消息；已被用户删除的会话显示状态，并可以永久删除；确认接口不能读取其他用户会话，页面没有编辑或导出操作。

- [ ] **Step 5: 验证会话软删除与永久删除流程**

普通用户删除自己的会话后，用户列表和读取接口都不可见，但数据库仍保留记录并标记“已被用户删除”；普通管理员不能操作；总管可以查看状态并永久删除，未软删除会话不能永久删除。

- [ ] **Step 6: 验证强制改密流程**

重置一个普通账号后确认旧令牌失效；使用 `123` 登录只能修改密码；输入正确原密码设置新密码后恢复聊天和原有上下文。

- [ ] **Step 7: 完整回归**

```bash
python -m unittest discover -s tests -v
python -m compileall main.py config.py agent_factory.py database.py models.py rag.py
git diff --check
```
