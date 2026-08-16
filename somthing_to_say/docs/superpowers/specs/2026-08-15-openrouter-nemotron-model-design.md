# OpenRouter Nemotron 模型切换设计

## 目标

将客服项目的主模型和降级/摘要模型切换为 `nvidia/nemotron-3.5-lightning:free`，通过 OpenRouter 的 OpenAI 兼容接口调用，并保持现有安全中间件、重试、熔断、工具和摘要流程不变。

## 架构

`config.py` 继续作为模型配置的唯一来源，保存模型名和 OpenRouter base URL。`agent_factory.py` 使用项目已有的 `langchain-openai` 依赖构造 `ChatOpenAI`，显式读取 `OPENROUTER_API_KEY`，避免把 OpenRouter 请求误交给当前的 DeepSeek provider。主模型与 fallback 使用同一模型，减少对旧 DeepSeek 凭据的依赖。

## 环境变量

- `OPENROUTER_API_KEY`：必填，仅从运行环境读取，不写入代码、测试或日志。
- `OPENROUTER_BASE_URL`：可选，默认 `https://openrouter.ai/api/v1`，便于本地或测试环境覆盖接口地址。

缺少 `OPENROUTER_API_KEY` 时，创建 Agent 应抛出明确的 `RuntimeError`，而不是继续使用错误的 provider 或产生隐晦的鉴权错误。

## 测试与验证

新增配置契约测试，验证模型名、默认 base URL、OpenRouter 客户端构造路径和缺少密钥时的显式错误。先运行 `python -m compileall config.py agent_factory.py`，再运行模型配置测试；完整测试依赖环境安装好项目 requirements 后执行。
