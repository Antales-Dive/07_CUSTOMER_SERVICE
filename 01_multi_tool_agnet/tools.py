from langchain_core.tools import tool

#2.用@tool装饰器定义3个工具函数
@tool
def getweather(city: str) -> str:
    """获取指定城市的天气信息"""
    # 这里可以调用实际的天气API获取数据
    data = {
        "北京": "晴，25°C",
        "上海": "多云，22°C",
        "广州": "雷阵雨，28°C"
    }
    return data.get(city, f"暂无{city}的天气信息")

@tool
def calculate(expression: str) -> str:
    """计算数学表达式的结果"""
    import re
    if not re.match(r'^[\d\s\+\-\*\/\.\(\)\%]+$', expression):
        return "错误：表达式包含非法字符"
    try:
        return str(eval(expression))
    except Exception as e:
        return f"计算错误: {e}"

@tool
def get_time() -> str:
    """获取当前时间"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")       
     
@tool
def search_recipe(dish: str) -> str:
    """根据菜名搜索菜谱，返回食材和做法"""
    recipes = {
        "番茄炒蛋": {
            "食材": "番茄2个、鸡蛋3个、盐、糖、葱花",
            "做法": "1.番茄切块，鸡蛋打散加少许盐；2.热锅倒油炒散鸡蛋盛出；3.再倒油炒番茄出汁，加糖调味；4.倒入鸡蛋翻炒，撒葱花出锅。"
        },
        "红烧肉": {
            "食材": "五花肉500g、冰糖、生抽、老抽、料酒、八角、桂皮、葱姜",
            "做法": "1.五花肉切块焯水；2.锅中炒糖色；3.放入肉块翻炒上色；4.加料酒、生抽、老抽、八角桂皮；5.加热水没过肉，小火炖60分钟；6.大火收汁。"
        },
        "可乐鸡翅": {
            "食材": "鸡翅8个、可乐1罐、生抽、老抽、姜片",
            "做法": "1.鸡翅划两刀焯水；2.热锅煎鸡翅至两面金黄；3.倒入可乐和生抽老抽；4.中小火煮20分钟；5.大火收汁至浓稠。"
        },
    }

    if dish in recipes:
        r = recipes[dish]
        return f"【{dish}】\n食材：{r['食材']}\n做法：{r['做法']}"
    else:
        return f"暂无「{dish}」的菜谱，试试：{', '.join(recipes.keys())}"
