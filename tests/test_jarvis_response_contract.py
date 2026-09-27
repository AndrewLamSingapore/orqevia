import pytest

from app.jarvis_response_contract import validate_user_facing_answer


@pytest.mark.parametrize("role,provider", [("OWNER", "local-1b"), ("OWNER", "local-4b"), ("MEMBER", "local-4b"), ("OWNER", "optional-cloud"), ("MEMBER", "offline-local")])
def test_identity_and_chinese_contract_is_role_and_provider_independent(role, provider):
    del role, provider
    assert validate_user_facing_answer("你叫什么名字？", "我是 JARVIS，很高兴为你服务。") == []


@pytest.mark.parametrize("answer,violation", [
    ("I am a large language model and do not have a name.", "product_identity_overridden"),
    ("A02 completed the request.", "internal_agent_prefix_exposed"),
    ("I can help you.", "jarvis_identity_missing"),
    ("My name is JARVIS.", "chinese_response_required"),
])
def test_identity_language_regressions_require_verification(answer, violation):
    assert violation in validate_user_facing_answer("你叫什么名字？", answer)


def test_explicit_language_override_is_respected_without_cosmetic_rewriting():
    assert validate_user_facing_answer("请用英文回答：你叫什么名字？", "My name is JARVIS.") == []
    assert 'english_response_required' in validate_user_facing_answer("请用英文回答：你叫什么名字？", "我是 JARVIS。")


def test_tool_and_rag_results_are_validated_as_final_answers():
    assert validate_user_facing_answer("请总结工具结果", "工具结果已验证；我是 JARVIS。") == []
    assert 'internal_agent_prefix_exposed' in validate_user_facing_answer("请总结检索结果", "responsibility.a02 says the result is safe")
