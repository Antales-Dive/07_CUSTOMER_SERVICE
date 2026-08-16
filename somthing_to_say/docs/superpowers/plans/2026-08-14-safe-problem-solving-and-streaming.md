# 安全问题解决与流式回复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将“帮我想办法”改为结构化问题解决模式，并为低风险回复增加受约束的 SSE 流式输出，同时对高风险和不确定内容采用保守安全路径。

**Architecture:** `safety.py` 独立负责快速规则、结构化输入审核、输出规则和安全兜底。`main.py` 按风险等级选择非流式保守路径或 Agent 异步流式路径；只有完整结束的回复保存到数据库。前端从 `/stream` 读取 SSE，旧 `/api/chat/{session_id}` 保留兼容。

**Tech Stack:** FastAPI `StreamingResponse`、LangChain Agent `astream`、原生 `ReadableStream`、SSE、Python 标准库规则扫描。

---

### Task 1: 定义模式和安全结果结构

**Files:**
- Modify: `models.py`
- Create: `safety.py`
- Test: `tests/test_safety.py`

- [ ] **Step 1: 写安全规则和模式测试**

覆盖 `companion`、`problem_solving` 两种用户模式；紧急状态由安全判断自动产生；正常负面情绪不被误判为紧急；明确自伤/伤人/危险操作进入保守路径；违法和诈骗请求被拒绝；输出滚动扫描能识别跨片段危险短语。

- [ ] **Step 2: 运行失败测试**

Run: `python -m unittest tests.test_safety -v`

Expected: 新模块和 `ChatRequest.mode` 尚不存在，新增测试失败。

- [ ] **Step 3: 增加模式和审核数据模型**

在 `models.py` 增加：

```python
ChatMode = Literal["companion", "problem_solving"]

class SafetyDecision(BaseModel):
    level: Literal["safe", "caution", "urgent", "disallowed"]
    reason_code: str

class OutputDecision(BaseModel):
    result: Literal["approved", "rewrite", "blocked"]
    reason_code: str
```

`ChatRequest` 增加 `mode: ChatMode = "companion"`。

- [ ] **Step 4: 实现 `safety.py` 规则边界**

实现以下可测试函数：

```python
def classify_input_rules(content: str) -> SafetyDecision: ...
def scan_output_window(window: str) -> bool: ...
def validate_output_rules(content: str) -> OutputDecision: ...
def safe_fallback(level: str) -> str: ...
```

规则不把“难受”“不想上课”等普通情绪词单独判为紧急；扫描窗口保留固定尾部长度以识别跨增量片段危险短语。规则函数不打印或保存原文。

- [ ] **Step 5: 运行安全规则测试**

Run: `python -m unittest tests.test_safety -v`

Expected: 规则、扫描窗口、兜底消息和模式校验通过。

- [ ] **Step 6: 提交安全基础层**

```bash
git add safety.py models.py tests/test_safety.py
git commit -m "feat: add safety modes and scanners"
```

### Task 2: 增加问题解决提示词和安全审核编排

**Files:**
- Modify: `config.py`
- Modify: `agent_factory.py`
- Modify: `main.py`
- Test: `tests/test_problem_solving_backend.py`

- [ ] **Step 1: 写问题解决提示词测试**

断言 `problem_solving` 提示词和 Skill 强调自然、简洁、行动导向的回答，并明确不提供医疗、法律、投资或危险指导；不再要求每次回复固定段落、方案数量或“今天的第一步”。

- [ ] **Step 2: 增加模式提示词选择**

在 `config.py` 增加独立的 `PROBLEM_SOLVING_PROMPT`；在 `build_agent` 增加 `mode` 参数，仅为 `problem_solving` 选择短回答提示词并限制模型输出长度；该模式不加载工具。

- [ ] **Step 3: 实现输入审核编排**

在 `main.py` 中先运行 `classify_input_rules`。命中 `urgent` 或 `disallowed` 时跳过普通 Agent；`caution` 或规则不确定时走完整安全路径；低风险才允许快速生成。审核异常转为保守结果，不把异常、模型原文或用户原文写入日志。

- [ ] **Step 4: 实现输出审核与最多一次重写**

完整路径生成后调用 `validate_output_rules`；不通过时带原因代码重写一次，再次不通过使用 `safe_fallback`。只有最终通过的内容才允许保存到 `messages`。

- [ ] **Step 5: 运行问题解决后端测试**

Run: `python -m unittest tests.test_problem_solving_backend -v`

Expected: 模式提示词、风险分流、重写上限和草稿不落库测试通过。

- [ ] **Step 6: 提交安全编排**

```bash
git add config.py agent_factory.py main.py tests/test_problem_solving_backend.py
git commit -m "feat: add structured problem solving safety flow"
```

### Task 3: 增加 SSE 流式接口

**Files:**
- Modify: `main.py`
- Test: `tests/test_streaming_backend.py`

- [ ] **Step 1: 写 SSE 事件测试**

使用假的 Agent 流验证事件顺序为 `start`、多个 `delta`、`done`；验证拼接内容等于最终消息；高风险只返回安全回复事件；客户端断开或 Agent 异常时不保存半截助手消息。

- [ ] **Step 2: 实现 SSE 编码器**

增加只接受结构化字段的 `sse_event(event, payload)`，使用 `json.dumps(..., ensure_ascii=False)` 编码，避免直接拼接用户输入。

- [ ] **Step 3: 实现 `/api/chat/{session_id}/stream`**

使用 `StreamingResponse` 和异步生成器：先验证用户及会话，写入用户消息，执行风险分流；快速路径读取 Agent `astream` 增量，滚动扫描命中则停止；保守路径只在审核通过后发送单个 `delta`。流正常结束且内容非空才写入助手消息。

- [ ] **Step 4: 保留非流式兼容接口**

保留 `/api/chat/{session_id}`，复用同一安全编排但返回完整 `ChatResponse`，不改变旧客户端契约。

- [ ] **Step 5: 运行流式后端测试**

Run: `python -m unittest tests.test_streaming_backend -v`

Expected: SSE 顺序、编码、风险阻断、断线不落库和兼容接口测试通过。

- [ ] **Step 6: 提交流式接口**

```bash
git add main.py tests/test_streaming_backend.py
git commit -m "feat: add safe streaming chat endpoint"
```

### Task 4: 接入前端模式和流式展示

**Files:**
- Modify: `static/index.html`
- Test: `tests/test_companion_ui.py`

- [ ] **Step 1: 写前端结构测试**

断言“帮我想办法”带有 `data-mode="problem_solving"`；请求体包含 `mode`；页面使用 `ReadableStream`、解析 `start`/`delta`/`done`/`error`；流失败时移除未完成气泡并恢复发送按钮。

- [ ] **Step 2: 保存会话模式状态**

增加当前会话模式变量；快捷入口设置模式；新会话恢复 `companion`；普通输入继续沿用当前会话模式。

- [ ] **Step 3: 实现 SSE 读取器**

增加 `streamChat`：使用 `response.body.getReader()` 按行解析 SSE，收到 `delta` 追加到助手气泡，收到 `done` 刷新会话列表；解析失败或浏览器不支持流式读取时回退到现有非流式 API。

- [ ] **Step 4: 实现加载和错误状态**

流式期间禁用发送按钮；先显示与当前用户模式匹配的动态等待状态，例如“正在理解你的意思…”或“正在整理可行的办法…”；状态定时轮换但不展示模型内部思维过程；收到首个 `delta` 后替换为真实回复。断线、`error` 或空回复时移除未完成气泡并显示可重试提示；不把半截内容当作成功消息。

- [ ] **Step 5: 运行前端测试和脚本检查**

Run: `python -m unittest tests.test_companion_ui -v`

Run: 提取 `static/index.html` 内联脚本后执行 `node --check <temporary-file>`。

Expected: 模式、SSE 解析、错误恢复和现有身份/上下文测试通过。

- [ ] **Step 6: 提交前端流式体验**

```bash
git add static/index.html tests/test_companion_ui.py
git commit -m "feat: stream safe chat responses"
```

### Task 5: 完整回归与浏览器验证

**Files:**
- Verify: `main.py`, `database.py`, `models.py`, `safety.py`, `agent_factory.py`, `static/index.html`, `tests/`

- [ ] **Step 1: 运行完整测试和编译检查**

```bash
python -m unittest discover -s tests -v
python -m compileall main.py config.py agent_factory.py database.py models.py rag.py safety.py
git diff --check
```

Expected: 全部测试通过，编译成功，无空白错误。

- [ ] **Step 2: 验证真实 SSE 响应**

启动本地服务，使用一个当前用户会话发送普通消息，确认收到 `start`、`delta`、`done`；确认数据库只保存最终助手回复，刷新后上下文完整。

- [ ] **Step 3: 验证问题解决模式**

点击“帮我想办法”，确认请求携带 `problem_solving`，回答短、包含方案和第一步；普通情绪消息不进入紧急流程。

- [ ] **Step 4: 验证高风险和输出阻断**

使用测试替身覆盖高风险输入、危险输出、审核失败和流中断，确认不泄露未审核草稿、不保存半截回复，并显示安全兜底。

- [ ] **Step 5: 验证桌面和移动端布局**

使用 Playwright 检查 `1366x820` 和 `390x844`，确认流式追加不会横向溢出、消息气泡稳定、发送按钮状态可恢复。
