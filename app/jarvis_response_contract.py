"""Provider-independent validation for the current public product identity."""

from __future__ import annotations

import re

from .agent_dispatch_api import requested_response_language
from .product_identity import PRODUCT_NAME


INTERNAL_PREFIX = re.compile(r'^\s*(?:responsibility\.)?a\d{2}\b', re.I)
NON_JARVIS_IDENTITY = re.compile(r"\b(?:i am|i'm)\s+(?:an?\s+)?(?:large\s+language\s+model|ai\s+model|assistant without a name)\b", re.I)
LEGACY_INTRODUCTION = re.compile(
    r"(?:\b(?:i am|i'm|my name is|call me)\s+|(?:我是|我叫|我的名字是)\s*)(?:JARVIS|PRIME)(?![a-z0-9_])", re.I
)
NAME_QUESTION = re.compile(r'(?:你叫什么名字|你是誰|你是谁|what(?:\s+is|\'s)\s+your\s+name|who\s+are\s+you)', re.I)
CHINESE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def validate_user_facing_answer(objective: str, answer: str) -> list[str]:
    violations: list[str] = []
    if not isinstance(answer, str) or not answer.strip():
        return ['missing_final_answer']
    if INTERNAL_PREFIX.search(answer):
        violations.append('internal_agent_prefix_exposed')
    if NON_JARVIS_IDENTITY.search(answer) or LEGACY_INTRODUCTION.search(answer):
        violations.append('product_identity_overridden')
    if NAME_QUESTION.search(objective) and PRODUCT_NAME not in answer:
        # Retain the legacy internal code for existing consumers.
        violations.append('jarvis_identity_missing')
    expected = requested_response_language(objective)
    # The fixed bilingual proper name is allowed in an English response and
    # cannot by itself count as a Chinese-language answer.
    has_chinese = bool(CHINESE.search(answer.replace(PRODUCT_NAME, '')))
    if expected == 'SIMPLIFIED_CHINESE' and not has_chinese:
        violations.append('chinese_response_required')
    if expected == 'ENGLISH' and has_chinese:
        violations.append('english_response_required')
    return violations
