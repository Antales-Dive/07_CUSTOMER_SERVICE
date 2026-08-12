from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
import tools

#1.模型初始化
model = init_chat_model(
    model="deepseek:deepseek-v4-flash",
    temperature=0,
    max_tokens=1024,
)


#3.创建agent
agent = create_agent(
    model=model,
    tools=[getweather, calculate, get_time],
    system_prompt="你是一个智能助手，可以回答天气、计算和时间相关的问题。"
)


#4.调用agent
resp = agent.invoke({
    "messages": [{"role": "user", "content": "北京的天气怎么样？再算一下1/0是多少？最后告诉我现在的时间。"}]
})

print(resp["messages"][-1].content)
