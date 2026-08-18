# 郑州大学只读校园资料 MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将可写的通用文件系统 MCP 替换为按需读取郑州大学官网公开资料的只读 MCP Server。

**Architecture:** 新增 Python stdio MCP Server，使用 FastMCP 暴露官方站内搜索、页面读取和官方入口列表。Server 对 URL、重定向、响应大小和内容类型强制校验；FastAPI 生命周期以当前 Python 解释器启动它，再通过现有 `MultiServerMCPClient` 注入陪伴模式 Agent。

**Tech Stack:** Python 3、MCP SDK `FastMCP`、标准库 `urllib`/`html.parser`、FastAPI、LangChain、`unittest`。

---

### Task 1: 锁定 URL 与 HTML 安全边界

**Files:**
- Create: `tests/test_zzu_campus_mcp.py`
- Create: `zzu_campus_mcp.py`

- [ ] **Step 1: 编写 URL 校验与 HTML 提取的失败测试**

```python
from zzu_campus_mcp import extract_page_text, validate_official_url


class OfficialUrlTests(unittest.TestCase):
    def test_accepts_root_domain_and_subdomain(self):
        self.assertEqual(validate_official_url("https://www.zzu.edu.cn/news.htm"), "https://www.zzu.edu.cn/news.htm")
        self.assertEqual(validate_official_url("http://jwc.zzu.edu.cn/"), "http://jwc.zzu.edu.cn/")

    def test_rejects_external_and_unsafe_urls(self):
        for value in (
            "https://example.com/",
            "https://zzu.edu.cn.evil.example/",
            "https://127.0.0.1/",
            "file:///etc/passwd",
            "https://user@www.zzu.edu.cn/",
            "https://www.zzu.edu.cn:8443/",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_official_url(value)

    def test_extract_page_text_ignores_scripts_and_styles(self):
        page = extract_page_text("<html><head><title>通知</title><style>hidden</style></head><body><script>secret</script><main>选课安排</main></body></html>")
        self.assertEqual(page["title"], "通知")
        self.assertIn("选课安排", page["text"])
        self.assertNotIn("hidden", page["text"])
        self.assertNotIn("secret", page["text"])
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m unittest tests.test_zzu_campus_mcp -v`

Expected: FAIL，提示 `zzu_campus_mcp` 模块或目标函数不存在。

- [ ] **Step 3: 实现纯函数和 HTML 文本解析器**

在 `zzu_campus_mcp.py` 中使用 `urlsplit`、`urlunsplit` 和 `ipaddress.ip_address` 实现以下函数：

```python
def validate_official_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("只支持郑州大学公开网页地址")
    if parsed.username or parsed.password or hostname == "zzu.edu.cn" and parsed.port not in {None, 80, 443}:
        raise ValueError("网页地址不符合只读资料访问规则")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("不允许使用 IP 地址访问")
    if hostname != "zzu.edu.cn" and not hostname.endswith(".zzu.edu.cn"):
        raise ValueError("只允许访问郑州大学官方域名")
    if parsed.port not in {None, 80 if parsed.scheme == "http" else 443}:
        raise ValueError("不允许使用非默认端口")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
```

实现继承 `HTMLParser` 的 `_ReadableTextParser`，在 `script`、`style`、`noscript`、`svg` 节点内忽略数据，收集 `title` 与正文文本。`extract_page_text(html)` 返回 `{"title": title, "text": normalized_text}`，将连续空白规范化为单个空格。

- [ ] **Step 4: 运行测试并确认通过**

Run: `python -m unittest tests.test_zzu_campus_mcp -v`

Expected: PASS，URL 规则和正文清洗均通过。

### Task 2: 实现受限 HTTP 获取与 MCP 工具

**Files:**
- Modify: `zzu_campus_mcp.py`
- Modify: `tests/test_zzu_campus_mcp.py`
- Modify: `config.py`

- [ ] **Step 1: 为重定向、响应限制和只读工具写失败测试**

在测试文件中加入可注入的伪 HTTP opener，并覆盖：

```python
def test_fetch_rejects_cross_domain_redirect(self):
    opener = FakeOpener(redirect_to="https://example.com/next")
    with self.assertRaises(ValueError):
        fetch_official_page("https://www.zzu.edu.cn/a.htm", opener=opener)

def test_fetch_rejects_oversized_and_non_html_responses(self):
    with self.assertRaises(ValueError):
        fetch_official_page("https://www.zzu.edu.cn/a.htm", opener=FakeOpener(content_type="application/pdf"))
    with self.assertRaises(ValueError):
        fetch_official_page("https://www.zzu.edu.cn/a.htm", opener=FakeOpener(body=b"x" * (ZZU_MAX_RESPONSE_BYTES + 1)))

def test_server_has_only_the_three_read_only_tools(self):
    self.assertEqual(set(TOOL_NAMES), {"search_zzu_official_site", "read_zzu_official_page", "list_zzu_official_sources"})
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m unittest tests.test_zzu_campus_mcp -v`

Expected: FAIL，HTTP 获取函数、配置常量或工具列表尚不存在。

- [ ] **Step 3: 添加固定非敏感配置**

在 `config.py` 添加：

```python
ZZU_OFFICIAL_DOMAIN = "zzu.edu.cn"
ZZU_SEARCH_URL = "https://www.zzu.edu.cn/ssjgy.jsp?wbtreeid=1001"
ZZU_HTTP_TIMEOUT_SECONDS = 10.0
ZZU_MAX_RESPONSE_BYTES = 1_000_000
ZZU_MAX_REDIRECTS = 3
ZZU_OFFICIAL_SOURCES = (
    ("郑州大学首页", "https://www.zzu.edu.cn/", "学校新闻与公开信息"),
    ("本科生院", "http://www5.zzu.edu.cn/jwc/", "选课、教务与教学通知"),
    ("研究生院", "http://gs.zzu.edu.cn/", "研究生培养与管理通知"),
    ("学生工作", "https://www.zzu.edu.cn/rcpy/xsgzwz.htm", "学生事务入口"),
)
```

- [ ] **Step 4: 实现受限获取和工具定义**

使用 `urllib.request.build_opener` 与禁止自动跳转的 `HTTPRedirectHandler`。每一跳都先调用 `validate_official_url`，最多跟随 `ZZU_MAX_REDIRECTS` 次；仅接受 `text/html`，读取 `ZZU_MAX_RESPONSE_BYTES + 1` 字节后拒绝超限响应。页面读取只发 GET；搜索仅向 `ZZU_SEARCH_URL` 发 URL 编码 POST，字段固定为：

```python
{
    "showkeycode": query.strip(),
    "lucenenewssearchkey": "",
    "_lucenesearchtype": "1",
    "searchScope": "0",
}
```

用 `FastMCP("郑州大学只读校园资料")` 注册三个返回字典的工具：

```python
@mcp.tool(description="搜索郑州大学官网公开资料，仅返回官方链接。")
def search_zzu_official_site(query: str) -> dict[str, object]: ...

@mcp.tool(description="读取郑州大学官网允许域名内的公开 HTML 页面。")
def read_zzu_official_page(url: str) -> dict[str, str]: ...

@mcp.tool(description="列出郑州大学常用官方资料入口。")
def list_zzu_official_sources() -> dict[str, object]: ...
```

所有网络异常转为不含堆栈的 `ValueError`；模块入口仅执行 `mcp.run(transport="stdio")`。

- [ ] **Step 5: 运行 MCP 单元测试**

Run: `python -m unittest tests.test_zzu_campus_mcp -v`

Expected: PASS，不访问真实网络，且没有写工具、跨域跳转或非 HTML 内容通路。

### Task 3: 用只读校园 MCP 替换文件系统 MCP

**Files:**
- Modify: `main.py:1-100`
- Modify: `main.py:305-321`
- Modify: `tests/test_companion_backend.py:60-70`

- [ ] **Step 1: 更新启动配置失败测试**

将现有 `test_mcp_launcher_supports_linux_and_windows` 替换为：

```python
def test_mcp_launcher_uses_the_read_only_python_server(self):
    main_source = read_source("main.py")
    self.assertIn('"zzu_official"', main_source)
    self.assertIn('"command": sys.executable', main_source)
    self.assertIn('"zzu_campus_mcp.py"', main_source)
    self.assertNotIn("@modelcontextprotocol/server-filesystem", main_source)
    self.assertNotIn('"write_file"', main_source)
```

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `python -m unittest tests.test_companion_backend.CompanionBackendSafetyContractTests.test_mcp_launcher_uses_the_read_only_python_server -v`

Expected: FAIL，应用仍启动文件系统 MCP。

- [ ] **Step 3: 替换 FastAPI 生命周期中的 MCP 客户端配置**

在 `main.py`：

1. 删除 `MCP_NPX_COMMAND`、`MCP_WORKSPACE` 导入、`_FILESYSTEM_TOOL_SCHEMAS` 和 `_normalize_mcp_tool_schemas`。
2. 添加 `from pathlib import Path`。
3. 在 `lifespan` 中替换为：

```python
server_path = str(Path(__file__).with_name("zzu_campus_mcp.py"))
client = MultiServerMCPClient(
    {
        "zzu_official": {
            "command": sys.executable,
            "args": [server_path],
            "transport": "stdio",
        },
    }
)
app.state.mcp_tools = await client.get_tools()
print(f"[启动] 已加载 {len(app.state.mcp_tools)} 个郑州大学只读 MCP 工具")
```

保留现有 `app.state.mcp_tools` 的 Agent 注入、陪伴模式启用和问题解决模式禁用逻辑，不改动聊天 API。

- [ ] **Step 4: 运行启动契约和回归测试**

Run: `python -m unittest tests.test_companion_backend tests.test_problem_solving_backend -v`

Expected: PASS，应用不再依赖 Node/npm 或通用文件系统 MCP，问题解决模式仍没有工具。

### Task 4: 固化 Agent 使用边界和项目文档

**Files:**
- Modify: `config.py`
- Modify: `tests/test_companion_backend.py`
- Modify: `README.md`

- [ ] **Step 1: 为官方来源边界写失败测试**

在 `test_system_prompt_contains_approved_safety_language` 的必需短语中加入：

```python
"郑州大学官网公开资料",
"引用工具返回的官方链接",
"不要猜测或编造校内规定",
```

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `python -m unittest tests.test_companion_backend.CompanionBackendSafetyContractTests.test_system_prompt_contains_approved_safety_language -v`

Expected: FAIL，系统提示词尚未约束校园资料 MCP 的使用方式。

- [ ] **Step 3: 更新提示词和 README**

在 `SYSTEM_PROMPT` 中加入以下边界：

```text
- 对郑州大学校内流程、通知、联系方式等事实性问题，可以使用“郑州大学官网公开资料”工具；只能依据工具返回的内容回答，并引用工具返回的官方链接。
- 工具未返回可靠资料时，明确说明未检索到官方依据，不要猜测或编造校内规定、日期、联系方式或办理流程。
```

将 README 中的“MCP 文件系统工具”和 Node/npm 启动前提替换为郑州大学只读校园资料 MCP，记录三个工具、允许域名、实时请求特性、无写操作、搜索依赖官网可用性，以及问题解决模式禁用 MCP 的边界。

- [ ] **Step 4: 运行完整回归测试**

Run: `python -m unittest discover -s tests -p "test_*.py"`

Expected: PASS，原有功能和新增只读 MCP 约束均通过。

- [ ] **Step 5: 进行真实官网的最小手工验证**

Run: `python -c "from zzu_campus_mcp import list_zzu_official_sources, read_zzu_official_page; print(list_zzu_official_sources()); print(read_zzu_official_page('https://www.zzu.edu.cn/')['source_url'])"`

Expected: 输出官方入口列表以及 `https://www.zzu.edu.cn/` 的来源 URL；不写入文件、不创建会话、不调用模型。
