

BANNED = ["色情", "暴力", "政治敏感","赌博", "诈骗", "毒品", "恐怖主义", "极端主义", "仇恨言论", "歧视言论"]

@before_model(can_jump_to=["end"])
def block_input(state:AgentState, runtime):
    messages = state["messages"]  #字典取值，不是.messages
    last_user = messages[-1]
    if last_user.type =="human" and any(w in last_user.content for w in BANNED):
        return{
            "jump_to": "end",
            "message": AIMessage(content="抱歉，我无法回答涉及敏感内容的问题。")
        }

@after_model(can_jump_to=["end"])
def block_sensitive(state:AgentState, runtime):
    messages = state["messages"]  #字典取值，不是.messages
    last = messages[-1]
    if last.type == "ai" and any(w in last.content for w in BANNED):
        return{
            "jump_to": "end",
            "message": AIMessage(content="抱歉，我无法回答涉及敏感内容的问题。")
        }
    return None