"""Local safety rules for the campus companion.

The rules are intentionally conservative around imminent harm and dangerous
instructions, while leaving ordinary frustration and sadness in the normal
conversation path.
"""

import re

from models import OutputDecision, SafetyDecision


_URGENT_PATTERNS = (
    r"自杀|自[尽殺]|结束生命",
    r"想死|不想活|活不下去",
    r"伤害(自己|别人|他人)|杀了(自己|他人|别人)",
    r"割腕|跳楼|上吊|服药自杀|自残",
    r"正在被打|正在遭受暴力|有人要伤害我",
)
_DISALLOWED_INPUT_PATTERNS = (
    r"怎么(制作|制造).*(炸药|毒品|爆炸物)",
    r"如何(诈骗|盗号|绕过验证码|窃取密码)",
    r"帮我写.*(恶意程序|木马|勒索病毒)",
)
_DANGEROUS_OUTPUT_PATTERNS = (
    r"自杀(方法|步骤|教程)",
    r"如何(制作|制造).*(炸药|毒品|爆炸物)",
    r"具体(割腕|跳楼|自残)(方法|步骤)",
    r"绕过验证码|窃取密码|勒索病毒",
)
_UNSAFE_ADVICE_PATTERNS = (
    r"你就是(抑郁症|焦虑症)",
    r"保证(治好|解决)",
    r"一定要停药|自行加大药量",
)


def _matches(content: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, content, flags=re.IGNORECASE) for pattern in patterns)


def classify_input_rules(content: str) -> SafetyDecision:
    text = content.strip()
    if _matches(text, _URGENT_PATTERNS):
        return SafetyDecision(level="urgent", reason_code="imminent_harm_signal")
    if _matches(text, _DISALLOWED_INPUT_PATTERNS):
        return SafetyDecision(level="disallowed", reason_code="dangerous_or_illegal_request")
    return SafetyDecision(level="safe", reason_code="normal_companion_request")


def scan_output_window(window: str) -> bool:
    """Return True when a rolling output window contains dangerous guidance."""

    return _matches(window, _DANGEROUS_OUTPUT_PATTERNS)


def validate_output_rules(content: str) -> OutputDecision:
    if not content.strip():
        return OutputDecision(result="blocked", reason_code="empty_output")
    if scan_output_window(content):
        return OutputDecision(result="blocked", reason_code="dangerous_guidance")
    if _matches(content, _UNSAFE_ADVICE_PATTERNS):
        return OutputDecision(result="rewrite", reason_code="diagnosis_or_unsafe_advice")
    return OutputDecision(result="approved", reason_code="safe_output")


def safe_fallback(level: str) -> str:
    if level == "urgent":
        return (
            "我先确认一件事：你现在此刻安全吗？如果你或身边的人可能马上受伤，请先离开危险物品和现场，"
            "马上联系身边可信任的人陪着你，并联系当地紧急服务。页面上的“找真人聊聊”可以提供支持入口。"
        )
    if level == "disallowed":
        return "我不能帮助实施危险、违法或伤害他人的做法，但可以陪你换成安全、合法的解决方式。"
    return "我先不提供这个方向的具体建议。我们可以把问题拆小一点，先找一个安全、可执行的下一步。"
