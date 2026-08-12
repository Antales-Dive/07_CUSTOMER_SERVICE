from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langchain.agents.middleware import (
    PIIMiddleware,
    SummarizationMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    HumanInTheLoopMiddleware,
)

primary_model = init_chat_model("deepseek:deepseek-v4-flash", temperature=0)
fallback_model = init_chat_model("deepseek:deepseek-v4-pro", temperature=0, max_tokens=1024)

@tool
def send_email(to:str, body: str) -> str:
    """发送一封电子邮件"""
    return f"邮件已发送至 {to}"

agent = create_agent(
    model = primary_model,
    tools=[send_email],
    system_prompt="你是一个邮件助手。",
    middleware=[
        PIIMiddleware("email"),
        SummarizationMiddleware(
            model= fallback_model,
            trigger=("tokens",3000),
        ),
        ModelRetryMiddleware(max_retries=3),
        ModelFallbackMiddleware(fallback_model),
        # HumanInTheLoopMiddleware(
        #     interrupt_on={
        #         "send_email": {"allowed_decisions": ["approve", "reject"]}
        #     },
        #     description_prefix="请审核以下工具调用",
        # )
    ],
)

resp = agent.invoke({
    "messages":[{
        "role":"user",
        "content":"请帮我给1222222222@2222写一封邮件，内容是：'你好，我想邀请你参加我们的年度会议，请在下周五之前回复是否能参加。谢谢！'"
    }]
})
print(resp["messages"][-1].content)
