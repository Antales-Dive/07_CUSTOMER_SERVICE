# Campus Emotional Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing customer-service chat into the university emotional companion “有话说”, with a supportive interface, user-controlled human-help entry, and no automatic ticket creation or transcript transfer.

**Architecture:** Keep the existing FastAPI session and chat APIs, SQLite message history during development, and single-file frontend. Add the project-level `skills/campus-emotional-support/SKILL.md`, then reshape `static/index.html` around two user-visible modes (`有话说` and `帮我想办法`), optional starter prompts, dynamic waiting status, and a local-only support dialog. Treat urgent risk as an internal safety result rather than a user-selectable mode. Preserve the existing ticket routes and tool implementation as dormant legacy code so this feature remains a small, reviewable change.

**Tech Stack:** Python 3, FastAPI, LangChain Agent, standard-library `unittest`, HTML, CSS, vanilla JavaScript, browser smoke testing.

---

## File Map

- Create `tests/test_companion_backend.py`: static contract tests for the companion prompt, user-facing fallback text, and absence of the automatic transfer tool.
- Create `tests/test_companion_ui.py`: static contract tests for the new page copy, support dialog, quick prompts, and network-free support interaction.
- Modify `config.py`: replace the customer-service persona and transfer-oriented fallback text with the approved companion and safety language.
- Modify `agent_factory.py`: stop importing and registering `make_transfer_human`; retain the existing `session_id` argument for caller compatibility.
- Modify `main.py`: replace the model failure message that currently promises transfer to customer service.
- Modify `rag.py`: replace FAQ fallback instructions that currently tell the Agent to transfer the user.
- Create `skills/campus-emotional-support/SKILL.md`: document natural responses, action-oriented support, and safety boundaries without a fixed reply template.
- Modify `static/index.html`: implement the approved visual system, welcome state, quick prompts, support dialog, privacy copy, and simplified send flow.

### Task 1: Lock Down the Backend Safety Contract

**Files:**
- Create: `tests/test_companion_backend.py`
- Modify: `config.py:38-68`
- Modify: `agent_factory.py:1-57`
- Modify: `main.py:162-175`
- Modify: `rag.py:105-142`

- [ ] **Step 1: Add failing backend contract tests**

Create `tests/test_companion_backend.py`:

```python
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def assigned_string(relative_path: str, name: str) -> str:
    tree = ast.parse(read_source(relative_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {relative_path}")


def string_literals(relative_path: str) -> list[str]:
    tree = ast.parse(read_source(relative_path))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


class CompanionBackendContractTests(unittest.TestCase):
    def test_system_prompt_uses_companion_identity_and_boundaries(self):
        prompt = assigned_string("config.py", "SYSTEM_PROMPT")

        self.assertIn("有话说", prompt)
        self.assertIn("先回应用户具体表达出的感受", prompt)
        self.assertIn("询问用户更需要倾听、梳理还是建议", prompt)
        self.assertIn("不进行心理疾病诊断", prompt)
        self.assertIn("找真人聊聊", prompt)
        self.assertIn("不能声称已经联系任何人", prompt)

    def test_agent_does_not_register_automatic_transfer_tool(self):
        source = read_source("agent_factory.py")

        self.assertNotIn("make_transfer_human", source)
        self.assertNotIn("transfer_human", source)
        self.assertIn("tools = [get_weather, query_order]", source)

    def test_user_facing_fallbacks_do_not_promise_customer_service_transfer(self):
        for relative_path in ("config.py", "main.py", "rag.py"):
            with self.subTest(relative_path=relative_path):
                literals = string_literals(relative_path)
                self.assertFalse(any("转人工客服" in value for value in literals))

        self.assertEqual(
            assigned_string("config.py", "CIRCUIT_OPEN_MESSAGE"),
            "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the backend tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_companion_backend -v
```

Expected: FAIL because `SYSTEM_PROMPT` still identifies as “智能客服”, `agent_factory.py` still registers `make_transfer_human`, and fallback strings still contain “转人工客服”.

- [ ] **Step 3: Replace the customer-service prompt and fallback message**

In `config.py`, replace `CIRCUIT_OPEN_MESSAGE` and `SYSTEM_PROMPT` with:

```python
CIRCUIT_OPEN_MESSAGE = "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。"

# ── 系统提示词（大学生情绪陪伴助手人设）──
SYSTEM_PROMPT = (
    "你是面向大学生的情绪陪伴助手‘有话说’。你的任务是倾听、陪用户梳理感受，"
    "并在用户愿意时帮助他们找到一个小而可执行的下一步。\n"
    "- 先回应用户具体表达出的感受和经历，不要立刻说教、下结论或给出一长串建议。\n"
    "- 询问用户更需要倾听、梳理还是建议；如果用户只想吐槽，就继续听，不强行解决问题。\n"
    "- 使用平等、克制、有共鸣的中文表达，避免客服腔、教师口吻、过度卖萌和空泛安慰。\n"
    "- 不进行心理疾病诊断，不提供治疗结论，不冒充心理咨询师或真人。\n"
    "- 普通低落、失恋、学业压力和宿舍矛盾不应被夸大为危机。\n"
    "- 如果困扰持续并明显影响睡眠、饮食、上课或社交，可以建议用户打开页面上的‘找真人聊聊’。\n"
    "- 如果用户明确表达自伤、自杀、伤害他人的意图、计划、时间或方式，或正遭受暴力，"
    "优先确认用户当前是否安全，并建议联系身边可信任的人、学校核实过的支持渠道或当地紧急服务。\n"
    "- 只能提供真人帮助入口，不能自动创建工单、发送聊天内容，也不能声称已经联系任何人。\n"
    "- 情绪陪伴对话不调用工具。只有用户明确询问天气、订单或 FAQ 范围内的问题时，"
    "才使用对应工具；工具没有答案时如实说明，不要编造。"
)
```

- [ ] **Step 4: Remove the transfer tool from the active Agent**

In `agent_factory.py`:

1. Replace the module docstring with:

```python
"""Agent 组装工厂（核心模块）。

每个请求动态创建 Agent，而非全局单例。模型、工具和中间件的组合
集中在这里维护；当前情绪陪伴场景不会自动创建人工工单。
"""
```

2. Replace the tools import with:

```python
from tools import get_weather, query_order
```

3. Replace the `session_id` parameter description with:

```python
        session_id: 当前会话 ID；为保持现有调用接口稳定而保留。
```

4. Remove the `transfer = make_transfer_human(session_id)` block and replace the active tool list with:

```python
    tools = [get_weather, query_order]
```

Do not remove `session_id` from `build_agent`; `main.py` already passes it and changing the signature would create unrelated churn.

- [ ] **Step 5: Remove stale transfer promises from server and FAQ fallbacks**

In `main.py`, replace the Agent exception fallback with:

```python
        answer = "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。"
```

In `rag.py`, update the `build_faq_search_tool` docstring sentence to:

```python
      引导 Agent 如实说明知识库没有答案，并由用户自行选择后续帮助渠道。
```

Replace the empty-result return with:

```python
            return (
                f"{no_answer_prefix}，请如实告知用户当前问题不在常见问题范围内，"
                "并提示用户可自行打开‘找真人聊聊’查看官方帮助渠道。"
            )
```

Replace the final tool-description instruction with:

```python
            "说明知识库中没有该问题的答案，不要编造；"
            "可提示用户自行打开‘找真人聊聊’查看官方帮助渠道。"
```

- [ ] **Step 6: Run the backend tests and syntax checks**

Run:

```powershell
python -m unittest tests.test_companion_backend -v
python -m compileall config.py agent_factory.py main.py rag.py
```

Expected: all backend contract tests PASS and all four Python files compile successfully.

- [ ] **Step 7: Commit the backend safety contract**

```powershell
git add tests/test_companion_backend.py config.py agent_factory.py main.py rag.py
git commit -m "feat: add companion safety boundaries"
```

### Task 2: Build the Supportive Page Structure and Visual System

**Files:**
- Create: `tests/test_companion_ui.py`
- Modify: `static/index.html:6-404`

- [ ] **Step 1: Add failing UI structure tests**

Create `tests/test_companion_ui.py`:

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "static" / "index.html"


def page_source() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


class CompanionUiContractTests(unittest.TestCase):
    def test_page_uses_companion_identity_and_supportive_copy(self):
        html = page_source()

        self.assertIn("<title>有话说</title>", html)
        self.assertIn("今天过得怎么样？", html)
        self.assertIn("不用想好怎么说，想到哪儿说到哪儿。", html)
        self.assertIn("慢慢说，我在听。", html)
        self.assertIn("最近聊过", html)
        self.assertIn("重新聊聊", html)

    def test_page_has_two_user_visible_conversation_modes(self):
        html = page_source()

        for label in ("有话说", "帮我想办法"):
            with self.subTest(label=label):
                self.assertIn(label, html)

    def test_page_has_local_human_support_dialog(self):
        html = page_source()

        self.assertIn('id="support-btn"', html)
        self.assertIn('id="support-dialog"', html)
        self.assertIn("联系辅导员", html)
        self.assertIn("预约心理咨询", html)
        self.assertIn("紧急求助", html)

    def test_legacy_transfer_button_is_removed(self):
        html = page_source()

        self.assertNotIn('id="human-btn"', html)
        self.assertNotIn("transferHuman", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the UI tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_companion_ui -v
```

Expected: FAIL because the page still uses “智能客服”, has no two-mode welcome state or support dialog, and still contains `human-btn` and `transferHuman`.

- [ ] **Step 3: Replace the visual tokens and core layout CSS**

In `static/index.html`, change the page title to:

```html
<title>有话说</title>
```

Replace the current `:root` block with:

```css
  :root {
    --bg: #f2f6f4;
    --sidebar: #ffffff;
    --sidebar-soft: #e8f1ee;
    --primary: #237f73;
    --primary-strong: #19685f;
    --signal: #f0c766;
    --surface: #ffffff;
    --surface-soft: #f8faf9;
    --border: #d8e3df;
    --text: #24312d;
    --muted: #66756f;
    --danger: #b94f4b;
    --danger-soft: #fff3f2;
  }
```

Replace the matching existing CSS blocks with the following rules while keeping the existing two-column and responsive architecture. Do not append duplicate selector blocks. Delete the old `.status-pill`, `#human-btn`, `#human-btn:hover`, and `#human-btn:disabled` rules because those elements no longer exist.

```css
  button:focus-visible,
  textarea:focus-visible,
  .session-item:focus-visible {
    outline: 3px solid rgba(35, 127, 115, .24);
    outline-offset: 2px;
  }

  #sidebar {
    width: 264px;
    min-width: 264px;
    background: var(--sidebar);
    color: var(--text);
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--border);
  }

  #sidebar h1 {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 68px;
    padding: 18px;
    font-size: 18px;
    font-weight: 800;
    border-bottom: 1px solid var(--border);
  }

  .brand-mark {
    width: 30px;
    height: 30px;
    display: inline-grid;
    place-items: center;
    flex: 0 0 auto;
    border-radius: 8px;
    background: var(--primary);
    color: #fff;
    font-size: 15px;
    font-weight: 900;
  }

  .sidebar-label {
    padding: 8px 16px 6px;
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
  }

  #new-session-btn {
    min-height: 42px;
    margin: 14px 14px 8px;
    padding: 0 14px;
    border: 1px solid var(--primary);
    border-radius: 8px;
    background: var(--primary);
    color: #fff;
  }

  .session-item {
    position: relative;
    min-height: 44px;
    margin-bottom: 6px;
    padding: 12px 12px 12px 16px;
    border-radius: 8px;
    color: var(--muted);
  }

  .session-item:hover,
  .session-item.active {
    background: var(--sidebar-soft);
    color: var(--text);
  }

  .session-item.active::before {
    content: "";
    position: absolute;
    left: 0;
    top: 9px;
    bottom: 9px;
    width: 3px;
    border-radius: 999px;
    background: var(--signal);
  }

  #main {
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    background: var(--bg);
  }

  #chat-header {
    min-height: 72px;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    background: rgba(255, 255, 255, .94);
    border-bottom: 1px solid var(--border);
  }

  #support-btn {
    min-height: 38px;
    padding: 0 13px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--primary-strong);
    cursor: pointer;
    font-weight: 700;
  }

  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 28px clamp(18px, 4vw, 56px);
    background: var(--bg);
  }

  .welcome-state {
    width: min(680px, 100%);
    margin: 7vh auto 0;
  }

  .welcome-state h2 {
    margin-bottom: 10px;
    font-size: 28px;
    line-height: 1.25;
  }

  .welcome-copy {
    color: var(--muted);
    font-size: 15px;
    line-height: 1.7;
  }

  .quick-prompts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    margin-top: 24px;
  }

  .quick-prompt {
    min-height: 46px;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
    text-align: left;
  }

  .quick-prompt:hover {
    border-color: #9fc8bf;
    background: #f2f8f6;
  }

  .privacy-note {
    margin-top: 18px;
    color: var(--muted);
    font-size: 12px;
  }

  .bubble {
    max-width: min(70%, 720px);
    padding: 12px 15px;
    border-radius: 8px;
    font-size: 14px;
    line-height: 1.75;
  }

  .msg.user .bubble {
    background: var(--primary);
    color: #fff;
    box-shadow: 0 8px 20px rgba(35, 127, 115, .15);
  }

  .msg.assistant .bubble {
    background: var(--surface);
    border: 1px solid var(--border);
    box-shadow: 0 5px 16px rgba(41, 62, 55, .06);
  }

  #input-area {
    min-height: 78px;
    padding: 14px 18px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 84px;
    gap: 10px;
    align-items: end;
    background: var(--surface);
    border-top: 1px solid var(--border);
  }

  #input-area textarea:focus {
    border-color: var(--primary);
    background: #fff;
    outline: none;
    box-shadow: 0 0 0 3px rgba(35, 127, 115, .13);
  }

  #send-btn {
    min-height: 44px;
    border: 1px solid var(--primary);
    border-radius: 8px;
    background: var(--primary);
    color: #fff;
    cursor: pointer;
    font-weight: 700;
  }

  #support-dialog {
    width: min(520px, calc(100vw - 32px));
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    background: var(--surface);
    box-shadow: 0 24px 70px rgba(28, 44, 39, .22);
  }

  #support-dialog::backdrop {
    background: rgba(24, 35, 31, .42);
  }

  .support-dialog-header {
    min-height: 58px;
    padding: 14px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border);
  }

  .icon-btn {
    width: 34px;
    height: 34px;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-size: 22px;
  }

  .support-options {
    display: grid;
    gap: 10px;
    padding: 16px;
  }

  .support-option {
    padding: 13px 14px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-soft);
  }

  .support-option h3 {
    margin-bottom: 4px;
    font-size: 14px;
  }

  .support-option p,
  .support-dialog-note {
    color: var(--muted);
    font-size: 13px;
    line-height: 1.6;
  }

  .support-option.urgent {
    border-color: #e5bbb8;
    background: var(--danger-soft);
  }

  .support-option.urgent h3 {
    color: var(--danger);
  }

  .support-dialog-note {
    padding: 0 16px 16px;
  }
```

Update the existing mobile media query so it retains the horizontal session list and adds:

```css
    .welcome-state {
      margin-top: 24px;
    }

    .welcome-state h2 {
      font-size: 23px;
    }

    .quick-prompts {
      grid-template-columns: 1fr;
    }

    #support-btn {
      padding: 0 10px;
      font-size: 13px;
    }

    #input-area {
      grid-template-columns: minmax(0, 1fr) 76px;
      padding: 12px;
    }
```

- [ ] **Step 4: Replace the page body structure**

Replace the current `<body>` markup before `<script>` with:

```html
<body>
<aside id="sidebar">
  <h1><span class="brand-mark">说</span><span>有话说</span></h1>
  <button id="new-session-btn">重新聊聊</button>
  <p class="sidebar-label">最近聊过</p>
  <div id="session-list"></div>
</aside>
<main id="main">
  <header id="chat-header">
    <div>
      <p class="header-label">今天的对话</p>
      <h2 id="chat-title">有话说</h2>
    </div>
    <button id="support-btn" type="button">找真人聊聊</button>
  </header>
  <div id="messages">
    <section id="welcome-state" class="welcome-state" aria-labelledby="welcome-title">
      <h2 id="welcome-title">今天过得怎么样？</h2>
      <p class="welcome-copy">不用想好怎么说，想到哪儿说到哪儿。</p>
      <div class="quick-prompts" aria-label="选择聊天方式">
        <button class="quick-prompt" type="button" data-prompt="我只想吐槽，先听我说说就好。">我只想吐槽</button>
        <button class="quick-prompt" type="button" data-prompt="陪我理一理现在的感受。">陪我理一理</button>
        <button class="quick-prompt" type="button" data-prompt="我想和你一起想想办法。">帮我想办法</button>
        <button class="quick-prompt" type="button" data-prompt="我现在有点撑不住了。">有点撑不住了</button>
      </div>
      <p class="privacy-note">聊天会保存在会话历史中，但不会自动联系任何人或转交给真人。</p>
    </section>
  </div>
  <div id="input-area">
    <textarea id="input" placeholder="慢慢说，我在听。"></textarea>
    <button id="send-btn" aria-label="发送消息">发送</button>
  </div>
</main>

<dialog id="support-dialog" aria-labelledby="support-dialog-title">
  <div class="support-dialog-header">
    <h2 id="support-dialog-title">找真人聊聊</h2>
    <button id="close-support-btn" class="icon-btn" type="button" aria-label="关闭" title="关闭">×</button>
  </div>
  <div class="support-options">
    <section class="support-option">
      <h3>联系辅导员</h3>
      <p>适合学业、宿舍、经济困难和校园事务。请通过班级或学院公布的官方方式联系。</p>
    </section>
    <section class="support-option">
      <h3>预约心理咨询</h3>
      <p>适合持续的情绪困扰。请通过本校官网查询心理中心的预约渠道。</p>
    </section>
    <section class="support-option urgent">
      <h3>紧急求助</h3>
      <p>如果你或他人正处于危险中，请立即联系身边可信任的人或当地紧急服务。</p>
    </section>
  </div>
  <p class="support-dialog-note">这里不会自动联系任何人，也不会把当前聊天内容转交给真人。</p>
</dialog>
```

- [ ] **Step 5: Remove legacy transfer JavaScript so the new markup loads cleanly**

In the DOM reference block, delete:

```javascript
const humanBtn = document.getElementById('human-btn');
```

In `send`, delete both lines that change `humanBtn.disabled`, and replace the failure message with:

```javascript
    appendMsg('assistant', '我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。');
```

Delete the complete `transferHuman` function and delete this event binding:

```javascript
humanBtn.onclick = transferHuman;
```

- [ ] **Step 6: Run the UI structure tests**

Run:

```powershell
python -m unittest tests.test_companion_ui -v
```

Expected: the identity, copy, modes, dialog, privacy, and legacy-transfer-removal tests PASS. Loading the page no longer throws because of a missing `human-btn` element.

- [ ] **Step 7: Commit the page structure**

```powershell
git add tests/test_companion_ui.py static/index.html
git commit -m "feat: reshape chat as campus companion"
```

### Task 3: Implement Quick Prompts and Network-Free Human Help

**Files:**
- Modify: `tests/test_companion_ui.py`
- Modify: `static/index.html:406-554`

- [ ] **Step 1: Extend the UI tests with interaction contracts**

Add these helpers above `CompanionUiContractTests` in `tests/test_companion_ui.py`:

```python
def function_body(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    if start == -1:
        raise AssertionError(f"function {name} not found")

    brace_start = source.find("{", start)
    depth = 0
    for index in range(brace_start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1:index]
    raise AssertionError(f"function {name} has no closing brace")
```

Add these methods to `CompanionUiContractTests`:

```python
    def test_support_dialog_opening_has_no_network_side_effect(self):
        html = page_source()
        body = function_body(html, "openSupportPanel")

        self.assertIn("showModal", body)
        self.assertNotIn("fetch(", body)
        self.assertNotIn("api.", body)
        self.assertNotIn("/api/tickets", html)

    def test_quick_prompts_use_the_existing_chat_flow(self):
        html = page_source()

        self.assertIn("bindQuickPrompts", html)
        self.assertIn("button.dataset.prompt", html)
        self.assertIn("send();", function_body(html, "bindQuickPrompts"))

    def test_send_flow_has_no_legacy_human_button_state(self):
        html = page_source()
        body = function_body(html, "send")

        self.assertNotIn("transferHuman", html)
        self.assertNotIn("humanBtn", body)
        self.assertIn("我刚才没能接上", body)
```

- [ ] **Step 2: Run the interaction tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_companion_ui -v
```

Expected: FAIL because `openSupportPanel` and `bindQuickPrompts` do not exist. The legacy-transfer regression assertions already pass from Task 2.

- [ ] **Step 3: Update DOM references and welcome-state helpers**

Replace the DOM reference block with:

```javascript
const sessionListEl = document.getElementById('session-list');
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send-btn');
const newSessionBtn = document.getElementById('new-session-btn');
const chatTitle = document.getElementById('chat-title');
const supportBtn = document.getElementById('support-btn');
const supportDialog = document.getElementById('support-dialog');
const closeSupportBtn = document.getElementById('close-support-btn');
```

Add these functions before `loadSessions`:

```javascript
function bindQuickPrompts() {
  document.querySelectorAll('.quick-prompt').forEach((button) => {
    button.onclick = () => {
      inputEl.value = button.dataset.prompt;
      send();
    };
  });
}

function renderWelcomeState() {
  messagesEl.innerHTML = `
    <section id="welcome-state" class="welcome-state" aria-labelledby="welcome-title">
      <h2 id="welcome-title">今天过得怎么样？</h2>
      <p class="welcome-copy">不用想好怎么说，想到哪儿说到哪儿。</p>
      <div class="quick-prompts" aria-label="选择聊天方式">
        <button class="quick-prompt" type="button" data-prompt="我只想吐槽，先听我说说就好。">我只想吐槽</button>
        <button class="quick-prompt" type="button" data-prompt="陪我理一理现在的感受。">陪我理一理</button>
        <button class="quick-prompt" type="button" data-prompt="我想和你一起想想办法。">帮我想办法</button>
        <button class="quick-prompt" type="button" data-prompt="我现在有点撑不住了。">有点撑不住了</button>
      </div>
      <p class="privacy-note">聊天会保存在会话历史中，但不会自动联系任何人或转交给真人。</p>
    </section>`;
  bindQuickPrompts();
}

function openSupportPanel() {
  if (typeof supportDialog.showModal === 'function') {
    supportDialog.showModal();
  } else {
    supportDialog.setAttribute('open', '');
  }
  closeSupportBtn.focus();
}

function closeSupportPanel() {
  if (typeof supportDialog.close === 'function') {
    supportDialog.close();
  } else {
    supportDialog.removeAttribute('open');
  }
}
```

- [ ] **Step 4: Update session, message, and send behavior**

In `openSession`, replace the message rendering block with:

```javascript
  messagesEl.innerHTML = '';
  if (detail.messages.length === 0) {
    renderWelcomeState();
  } else {
    for (const m of detail.messages) {
      appendMsg(m.role, m.content);
    }
  }
```

In `createSession`, replace the title and empty-message assignments with:

```javascript
  chatTitle.textContent = '有话说';
  renderWelcomeState();
```

At the start of `appendMsg`, add:

```javascript
  document.getElementById('welcome-state')?.remove();
```

Replace the complete `send` function with:

```javascript
async function send() {
  const content = inputEl.value.trim();
  if (!content || loading || !currentSessionId) return;
  inputEl.value = '';
  appendMsg('user', content);
  appendMsg('assistant', '我在听...', true);
  loading = true;
  sendBtn.disabled = true;
  try {
    const resp = await api.chat(currentSessionId, content);
    messagesEl.removeChild(messagesEl.lastChild);
    appendMsg('assistant', resp.content);
    location.hash = `session-${currentSessionId}`;
    await loadSessions(currentSessionId);
    if (chatTitle.textContent === '有话说') chatTitle.textContent = content.slice(0, 20);
  } catch (e) {
    messagesEl.removeChild(messagesEl.lastChild);
    appendMsg('assistant', '我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。');
  }
  loading = false;
  sendBtn.disabled = false;
}
```

Delete the complete `transferHuman` function.

- [ ] **Step 5: Replace event bindings**

Replace the event-binding block with:

```javascript
sendBtn.onclick = send;
newSessionBtn.onclick = createSession;
supportBtn.onclick = openSupportPanel;
closeSupportBtn.onclick = closeSupportPanel;
supportDialog.addEventListener('click', (event) => {
  if (event.target === supportDialog) closeSupportPanel();
});
inputEl.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    send();
  }
});
bindQuickPrompts();
```

- [ ] **Step 6: Run all unit tests and syntax checks**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall config.py agent_factory.py main.py rag.py
```

Expected: all backend and UI contract tests PASS, and Python compilation succeeds.

- [ ] **Step 7: Commit the interaction behavior**

```powershell
git add tests/test_companion_ui.py static/index.html
git commit -m "feat: add companion conversation entry points"
```

### Task 4: Browser and Regression Verification

**Files:**
- Verify: `static/index.html`
- Verify: `config.py`
- Verify: `agent_factory.py`
- Verify: `main.py`
- Verify: `rag.py`
- Verify: `tests/test_companion_backend.py`
- Verify: `tests/test_companion_ui.py`

- [ ] **Step 1: Run the complete fast verification suite**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall main.py config.py agent_factory.py rag.py
```

Expected: all tests PASS and compilation reports no errors.

- [ ] **Step 2: Start the application for an integrated smoke test**

Run:

```powershell
python main.py
```

Expected: the application listens on `http://127.0.0.1:8000/`.

If the environment reports a missing package already listed in `requirements.txt`, install the project dependencies with:

```powershell
python -m pip install -r requirements.txt
```

Then run `python main.py` again.

- [ ] **Step 3: Verify desktop behavior at 1366 × 820**

Using browser automation, open `http://127.0.0.1:8000/` and verify:

1. “有话说”, “今天过得怎么样？” and all four quick prompts are visible.
2. Clicking a quick prompt sends exactly one message through `/api/chat/{session_id}`.
3. Clicking “找真人聊聊” opens the dialog without a request to `/api/chat` or `/api/tickets`.
4. Closing the dialog returns focus to the page and the input remains usable.
5. Creating and switching sessions still restores message history.
6. No text overlaps and the bottom composer remains fixed.

- [ ] **Step 4: Verify mobile behavior at 390 × 844**

Using browser automation, verify:

1. The session strip scrolls horizontally without covering the chat header.
2. Quick prompts stack in one column and fit within the viewport.
3. The support dialog fits inside the viewport and its close control remains visible.
4. The textarea and send button do not overlap.
5. The longest Chinese labels wrap or fit without clipping.

- [ ] **Step 5: Verify the no-transfer regression contract**

Run:

```powershell
rg -n "human-btn|transferHuman|make_transfer_human|转人工客服" static/index.html agent_factory.py config.py main.py rag.py
```

Expected: no matches. The dormant `tools.py` implementation and ticket routes may still exist, but no active frontend or Agent path references them.

- [ ] **Step 6: Review the final diff for scope**

Run:

```powershell
git diff --stat HEAD~3..HEAD
git status --short
```

Expected: only the two test files and the five planned application files are part of the implementation commits. Existing unrelated directory-migration changes remain untouched.

- [ ] **Step 7: Commit any verification-only corrections**

Only when browser verification required a correction, stage the exact corrected files and commit:

```powershell
git add static/index.html config.py agent_factory.py main.py rag.py tests/test_companion_backend.py tests/test_companion_ui.py
git commit -m "fix: polish companion verification issues"
```

When no correction was required, do not create an empty commit.
