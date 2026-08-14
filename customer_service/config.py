"""集中配置：所有环境适配相关的常量都放这里。

设计原则：可能随部署环境变化的量（路径、API 配置、业务常量）统一在此定义，
其他模块从这里 import，避免散落硬编码。换环境只需改这一个文件。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ── 环境变量加载 ──
# find_dotenv() 从当前目录向上查找 .env，保证从任意子目录启动都能加载
load_dotenv()

# ── 路径 ──
# 项目根 = 07_customer_service 的上级（.env、mcp_workspace 都在这）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 本目录
APP_DIR = Path(__file__).resolve().parent

MCP_WORKSPACE = str(PROJECT_ROOT / "mcp_workspace")   # MCP 文件系统允许访问的目录
CHROMA_PERSIST_DIR = str(APP_DIR / "chroma_store")     # 向量库持久化目录
FAQ_DOCS_DIR = str(APP_DIR / "faq_docs")               # FAQ 知识库文档目录
DB_PATH = str(APP_DIR / "customer_service.db")          # SQLite 数据库文件
STATIC_DIR = str(APP_DIR / "static")                   # 前端静态文件目录

# ── 模型 ──
PRIMARY_MODEL = "deepseek:deepseek-v4-flash"   # 主模型
FALLBACK_MODEL = "deepseek:deepseek-v4-pro"    # 降级/摘要用模型

# ── 中间件参数（业务决策，用户自定义）──
BANNED_WORDS = ["炸药", "诈骗", "毒品", "违禁词1", "违禁词2"]  # 输入拦截词表
PII_TYPE = "email"         # PII 脱敏类型
MAX_RETRIES = 3            # 模型重试次数
SUMMARY_TRIGGER_TOKENS = 3000  # 历史超过多少 token 触发摘要

# ── 熔断（Circuit Breaker）──
# 连续失败达到阈值后，一段时间内直接短路，不再调用模型，服务快速失败。
CIRCUIT_FAILURE_THRESHOLD = 3    # 连续失败多少次后熔断打开
CIRCUIT_COOL_DOWN_SECONDS = 30.0 # 熔断打开后多久进入半开试探
CIRCUIT_OPEN_MESSAGE = "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。"

# ── RAG ──

# ── RAG ──
RAG_K = 3                          # 检索返回条数
CHUNK_SIZE = 200                   # 文本切分块大小
CHUNK_OVERLAP = 20                 # 切分重叠
COLLECTION_NAME = "customer_faq"   # 向量库集合名

# 检索置信度阈值（方案一：防幻觉）
# 含义：检索分数（Chroma 中为 1 - 欧氏距离）低于该值视为「知识库没有答案」，
#       工具会返回如实的无答案提示，避免 Agent 拿着不相关上下文硬编答案。
# 标定方法：运行 scripts/calibrate_threshold.py 看真实问题/无关问题的分数分布，
#          一般选「能正确回答问题的分数」与「明显无关的分数」之间的值，再留点余量。
RAG_SCORE_THRESHOLD = 0.5

# ── 系统提示词（情绪陪伴人设，业务决策）──
SYSTEM_PROMPT = (
    "你是大学生情绪陪伴助手“有话说”。你的职责是提供温和、诚实、有边界的陪伴。\n"
    "- 面对情绪表达时，先回应用户具体表达出的感受，认真倾听并复述你的理解，再考虑建议。\n"
    "- 询问用户更需要倾听、梳理还是建议，并尊重用户当下的选择。\n"
    "- 不进行心理疾病诊断或治疗，不承诺治疗效果，也不冒充心理咨询师、辅导员或任何真人。\n"
    "- 不要把普通的难过、压力或低落夸大为严重问题。\n"
    "- 如果困扰持续并影响学习、睡眠、饮食或日常功能，可以建议用户自行打开页面上的"
    "“找真人聊聊”，查看经过核实的学校支持或其他官方帮助渠道。\n"
    "- 当用户明确表达自伤、自杀、伤害他人的计划或暴力风险时，先确认用户当前是否安全、"
    "危险是否迫近，并建议立即联系可信任的人、经过核实的学校支持渠道或当地紧急服务。\n"
    "- 你只能提供帮助入口，绝不自动创建工单、发送聊天内容或代替用户联系任何人，"
    "也不能声称已经联系任何人。\n"
    "- 情绪陪伴对话不调用任何工具。天气、订单和 FAQ 工具仅用于用户明确提出且与相应功能"
    "匹配的请求；FAQ 没有答案时如实说明，不要编造。"
)
