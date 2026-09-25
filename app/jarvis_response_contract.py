"""Provider-independent validation for the governed JARVIS final answer."""

from __future__ import annotations

import re

from .agent_dispatch_api import requested_response_language


INTERNAL_PREFIX = re.compile(r'^\s*(?:responsibility\.)?a\d{2}\b', re.I)
NON_JARVIS_IDENTITY = re.compile(r"\b(?:i am|i'm)\s+(?:an?\s+)?(?:large\s+language\s+model|ai\s+model|assistant without a name)\b", re.I)
NAME_QUESTION = re.compile(r'(?:你叫什么名字|你是誰|你是谁|what(?:\s+is|\'s)\s+your\s+name|who\s+are\s+you)', re.I)
CHINESE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def validate_user_facing_answer(objective: str, answer: str) -> list[str]:
    violations: list[str] = []
    if not isinstance(answer, str) or not answer.strip():
        return ['missing_final_answer']
    if INTERNAL_PREFIX.search(answer):
        violations.append('internal_agent_prefix_exposed')
    if NON_JARVIS_IDENTITY.search(answer):
        violations.append('product_identity_overridden')
    if NAME_QUESTION.search(objective) and 'JARVIS' not in answer.upper():
        violations.append('jarvis_identity_missing')
    expected = requested_response_language(objective)
    has_chinese = bool(CHINESE.search(answer))
    if expected == 'SIMPLIFIED_CHINESE' and not has_chinese:
        violations.append('chinese_response_required')
    if expected == 'ENGLISH' and has_chinese:
        violations.append('english_response_required')
    return violations
