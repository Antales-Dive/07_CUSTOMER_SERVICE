# Customer Service Ops UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the existing customer service chat page into a stable, readable support workbench.

**Architecture:** Keep the current single-file static frontend and existing FastAPI endpoints. Replace the visual structure and CSS in `static/index.html`, while preserving the API wrapper, session flow, message sending, transfer-to-human flow, and hash-based session restore.

**Tech Stack:** HTML, CSS, vanilla JavaScript, FastAPI static file serving.

---

### Task 1: Workbench Layout And Visual System

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Replace the page CSS with workbench tokens and responsive layout**

Use CSS custom properties for the approved palette:

```css
:root {
  --bg: #eef2f7;
  --sidebar: #17212f;
  --sidebar-soft: #22344a;
  --primary: #2f6fed;
  --primary-strong: #255dcc;
  --signal: #f2c14e;
  --surface: #ffffff;
  --surface-soft: #f8fafc;
  --border: #d8e0eb;
  --text: #172033;
  --muted: #66758a;
  --danger-soft: #fff7ed;
  --danger-border: #fed7aa;
}
```

The layout remains `#sidebar` plus `#main` on desktop. Under `760px`, switch `body` to column layout, make the sidebar a top region, and make `#session-list` horizontally scrollable.

- [ ] **Step 2: Update the static HTML shell**

Change the sidebar title to include a small brand mark and label. Change the chat header from plain text to a title group:

```html
<div id="chat-header">
  <div>
    <p class="header-label">当前会话</p>
    <h2 id="chat-title">客服助手</h2>
  </div>
  <span class="status-pill">在线处理</span>
</div>
```

Add `aria-label` values to the action buttons:

```html
<button id="human-btn" aria-label="转人工客服">转人工</button>
<button id="send-btn" aria-label="发送消息">发送</button>
```

- [ ] **Step 3: Update JavaScript references for the new title element**

Add:

```js
const chatTitle = document.getElementById('chat-title');
```

Replace `chatHeader.textContent = ...` title writes with `chatTitle.textContent = ...`. Preserve all current API calls and message flow.

- [ ] **Step 4: Improve interaction states without changing behavior**

When `send()` starts, set both `sendBtn.disabled = true` and `humanBtn.disabled = true`. In both success and error paths after completion, set both back to `false`. In `transferHuman()`, do the same for both buttons.

- [ ] **Step 5: Run the fastest syntax check**

Run:

```powershell
python -m compileall main.py config.py
```

Expected: both files compile successfully.

- [ ] **Step 6: Run a browser smoke check**

Start the app:

```powershell
python main.py
```

Open `http://127.0.0.1:8000/` and verify:

- The page loads.
- A new session is created.
- The chat header title updates for new/opened sessions.
- Buttons keep stable dimensions.
- Desktop and narrow widths do not show overlapping text.

If model credentials or provider services are unavailable, skip validating real AI response quality and only verify the frontend loads and event handlers are still attached.
