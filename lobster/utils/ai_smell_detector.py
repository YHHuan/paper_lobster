"""AI writing pattern detector.

Last quality gate before publishing. Checks for common AI writing tells.
"""

import re
import logging

logger = logging.getLogger("lobster.utils.ai_smell")

BANNED_PHRASES_ZH = [
    "在這個", "讓我們", "重磅", "震撼", "炸裂", "絕了",
    "毋庸置疑", "眾所周知", "值得注意的是", "有趣的是",
    "總的來說", "綜上所述", "總而言之",
    "不僅", "更是", "不只是", "而是",
    "讓我們來看看", "讓我們深入探討",
    "在這個快速變化", "在這個AI時代",
    "研究指出", "文獻顯示",
    "我直接", "家人們",
]

BANNED_PHRASES_EN = [
    "in this era", "let's dive", "it's worth noting",
    "needless to say", "in conclusion", "moreover",
    "furthermore", "delve into", "unleash",
    "it is important to note", "interestingly",
    "in today's rapidly", "game-changer",
    "revolutionize", "paradigm shift",
    "deep dive", "unpack",
]

# Emoji that should not start a post
OPENING_EMOJI_PATTERN = re.compile(r'^[\U0001F300-\U0001FAD6\u2600-\u27BF\u2702-\u27B0]')

# Three-point summary pattern
THREE_POINT_ZH = re.compile(r'[一二三四五]是.*?[一二三四五]是.*?[一二三四五]是', re.DOTALL)
THREE_POINT_EN = re.compile(r'(?:First|1\))[^.]*(?:Second|2\))[^.]*(?:Third|3\))', re.DOTALL)

# Excessive em-dash (Chinese full-width)
EM_DASH_PATTERN = re.compile(r'——')


class AISmellDetector:
    def check(self, draft: str, language: str) -> tuple[bool, list[str]]:
        """Check a draft for AI writing patterns.

        Returns:
            (passed, issues): passed=True if clean, issues=list of problems found.
        """
        issues = []
        draft_lower = draft.lower()

        # 1. Banned phrases
        phrases = BANNED_PHRASES_ZH if language == "zh" else BANNED_PHRASES_EN
        for phrase in phrases:
            if phrase.lower() in draft_lower:
                issues.append(f"banned phrase: '{phrase}'")

        # 2. Opening emoji
        if OPENING_EMOJI_PATTERN.match(draft.strip()):
            issues.append("starts with emoji")

        # 3. Three-point summary structure
        pattern = THREE_POINT_ZH if language == "zh" else THREE_POINT_EN
        if pattern.search(draft):
            issues.append("three-point summary structure")

        # 4. Excessive paired constructions (Chinese)
        if language == "zh":
            pairs = re.findall(r'不僅.*?更.*?[。\n]', draft)
            if len(pairs) >= 2:
                issues.append("excessive paired constructions")

        # 5. Excessive em-dashes (Chinese)
        if language == "zh":
            em_count = len(EM_DASH_PATTERN.findall(draft))
            if em_count > 2:
                issues.append(f"excessive em-dashes ({em_count} found, max 2)")

        # 6. Overly long connective chains (English)
        if language == "en":
            connectives = re.findall(
                r'\b(however|moreover|furthermore|additionally|consequently|nevertheless)\b',
                draft_lower
            )
            if len(connectives) >= 3:
                issues.append(f"excessive connectives ({len(connectives)} found)")

        passed = len(issues) == 0
        if not passed:
            logger.info(f"AI smell check failed: {issues}")
        return passed, issues
