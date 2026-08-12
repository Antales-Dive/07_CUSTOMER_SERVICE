"""LangChain 文档 RAG Agent —— 带检索增强 + 接地检查。

依赖安装：
    pip install "langchain>=1.2" langchain-openai langchain-deepseek \
                langchain-chroma langchain-text-splitters

环境变量：
    export OPENAI_API_KEY="sk-..."       # embedding 用
    export DEEPSEEK_API_KEY="sk-..."     # chat 用
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain.agents.middleware import after_model, AgentState
from langchain.chat_models import init_chat_model
from langchain_core.tools.retriever import create_retriever_tool
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, RemoveMessage
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 集中配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
load_dotenv()  # 读取项目根目录的 .env 文件

MODEL_NAME       = os.getenv("CHAT_MODEL", "deepseek:deepseek-v4-flash")
OLLAMA_BASE_URL  = os.getenv("OLLAMA_BASE_URL")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL")
CHUNK_SIZE       = 200
CHUNK_OVERLAP    = 20
RETRIEVER_K      = 3
PERSIST_DIR      = Path("./chroma_store")
COLLECTION_NAME  = "langchain_docs_ollama"

SYSTEM_PROMPT = (
    "你是 LangChain 文档助手。\n"
    "- 回答必须基于检索到的资料，不要编造。\n"
    "- 如果资料不足以回答，明确告知用户'知识库中暂无相关信息'。\n"
    "- 回答末尾附上引用来源编号。"
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 文档准备（demo 用；生产换 DirectoryLoader）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def load_documents() -> list[Document]:
    raw_texts = [
        "LangChain 1.0 于 2025 年 10 月发布，核心入口是 create_agent。",
        "Middleware 是 1.0 最重要的新特性，支持 before_model、after_model 等钩子。",
        "can_jump_to 参数用于声明钩子可以跳转到 end、model 或 tools 节点。",
        "init_chat_model 支持 'provider:model' 格式，如 'deepseek:deepseek-chat'。",
    ]
    return [
        Document(page_content=t, metadata={"source": f"doc_{i}"})
        for i, t in enumerate(raw_texts)
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 向量库（带持久化，避免重复 embedding）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_embeddings():
    return OllamaEmbeddings(
        model=OLLAMA_EMBEDDING_MODEL,
        base_url=OLLAMA_BASE_URL,
    )


def build_vectorstore(docs: list[Document]) -> Chroma:
    embeddings = build_embeddings()

    # 仅当已有持久化且目标集合非空时才复用，否则重建（避免空集合 + 旧向量空间问题）
    db_file = PERSIST_DIR / "chroma.sqlite3"
    if db_file.exists():
        existing = Chroma(
            persist_directory=str(PERSIST_DIR),
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME,
        )
        if existing._collection.count() > 0:
            logger.info("加载已有向量库：%s", PERSIST_DIR)
            return existing
        logger.info("集合 %s 为空，重建向量库", COLLECTION_NAME)

    logger.info("构建新向量库（%d 篇文档）", len(docs))
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)

    store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(PERSIST_DIR),
    )
    return store


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 检索工具
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_search_tool(vectorstore: Chroma):
    retriever = vectorstore.as_retriever(search_kwargs={"k": RETRIEVER_K})
    return create_retriever_tool(
        retriever,
        name="search_langchain_docs",
        description=(
            "搜索 LangChain 1.x 官方文档。"
            "适用于：API 用法、中间件、Agent 创建、模型初始化等问题。"
        ),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. after_model 钩子（接地检查）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_NO_ANSWER_SIGNALS = ("知识库中暂无", "未找到相关", "无法从资料中")


@after_model(can_jump_to=["end"])
def check_grounding(state: AgentState, runtime: Any):
    """如果模型明确表示无法回答，替换输出并提前终止。"""
    last = state["messages"][-1]

    # 只检查 AI 消息
    if last.type != "ai" or not last.content:
        return None

    # 多信号匹配，降低误判
    if any(sig in last.content for sig in _NO_ANSWER_SIGNALS):
        logger.warning("模型判定无法回答，提前终止")
        return {
            "jump_to": "end",
            "messages": [
                RemoveMessage(id=last.id),  # 删除原始的"无法回答"消息
                AIMessage(
                    content="📭 抱歉，当前知识库中未找到与您问题相关的资料，请尝试换个问法。",
                    additional_kwargs={"grounding_failed": True},
                ),
            ],
        }
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. Agent 工厂
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_agent(
    *,
    docs: list[Document] | None = None,
    model: Any | None = None,
    model_name: str = MODEL_NAME,
    temperature: float = 0,
    system_prompt: str = SYSTEM_PROMPT,
    tools: list[Any] | None = None,
    middleware: list[Any] | None = None,
):
    """通用的文档 RAG Agent 工厂，各部分可单独注入覆盖。"""
    docs = docs if docs is not None else load_documents()
    vectorstore = build_vectorstore(docs)
    search_tool = build_search_tool(vectorstore)
    model = model or init_chat_model(model_name, temperature=temperature)

    return create_agent(
        model=model,
        tools=tools if tools is not None else [search_tool],
        system_prompt=system_prompt,
        middleware=middleware if middleware is not None else [check_grounding],
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. 入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    # Windows 控制台默认 GBK，重设为 UTF-8 避免打印 emoji 时崩溃
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    agent = build_agent()

    question = "LangChain 1.0 的核心入口是什么？"
    logger.info("用户提问：%s", question)

    try:
        resp = agent.invoke({
            "messages": [{"role": "user", "content": question}],
        })
        answer = resp["messages"][-1].content
        print(f"\n回答：{answer}")

    except KeyboardInterrupt:
        print("\n⏹  用户中断")
    except Exception:
        logger.exception("Agent 执行失败")
        raise


if __name__ == "__main__":
    main()