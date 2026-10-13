"""Source prompt coverage of all 21 roles; these tests execute no model."""

import ast
import hashlib
from pathlib import Path

import pytest

from app.agent_dispatch_api import (
    AgentRequest, JARVIS_IDENTITY_CONTRACT, ORQEVIA_IDENTITY_CONTRACT, inference_prompt,
)
from app.agent_coaching import effective_prompt
from app.agent_registry import load_agent_registry
from app.jarvis_response_contract import validate_user_facing_answer
from app.product_identity import IDENTITY_CONTRACT, PRODUCT_NAME
from app.tier_router import Tier


@pytest.mark.parametrize('agent', load_agent_registry()['agents'], ids=lambda agent: agent['id'])
def test_all_21_roles_use_the_current_identity_and_preserve_their_output_contracts(agent):
    for responsibility in agent['responsibilities']:
        for tier in (Tier.NANO, Tier.MINI, Tier.FLAGSHIP):
            for context in ('', 'Supplied evidence; no execution authority.'):
                request = AgentRequest(capability=responsibility['id'], objective='What is your name?', context=context)
                before = request.model_dump_json()
                prompt = inference_prompt(request, tier)
                assert prompt.startswith(IDENTITY_CONTRACT)
                assert PRODUCT_NAME in prompt
                assert 'You are JARVIS' not in prompt
                assert 'Always identify yourself as JARVIS' not in prompt
                assert request.model_dump_json() == before
            structured = AgentRequest(
                capability=responsibility['id'], objective='Return the supplied facts.',
                context='evidence=retained-token', response_format='strict_json',
            )
            before = structured.model_dump_json()
            prompt = inference_prompt(structured, tier)
            assert f'You are a registered {PRODUCT_NAME} advisory worker' in prompt
            assert 'without a name, preface, Markdown, or code fence' in prompt
            assert prompt.endswith('Objective:\n'+structured.objective+'\nContext:\n'+structured.context)
            assert structured.model_dump_json() == before
    assert validate_user_facing_answer('What is your name? Reply in English.', f'My name is {PRODUCT_NAME}.') == []
    assert validate_user_facing_answer('你叫什么名字？', f'我是 {PRODUCT_NAME}。') == []


def test_legacy_internal_import_name_resolves_to_current_identity():
    assert ORQEVIA_IDENTITY_CONTRACT == JARVIS_IDENTITY_CONTRACT == IDENTITY_CONTRACT


def test_rebrand_does_not_change_retained_synthetic_coaching_prompt():
    # The pinned baseline manifest validates this exact existing prompt digest.
    _, prompt = effective_prompt('a01', 'baseline', 1001)
    assert hashlib.sha256(prompt.encode()).hexdigest() == 'fc4bffb21a711b92d18a0fd03df4fdc0f8adb0d07ff9c5769219642df59af61f'


def test_legacy_system_prompt_and_internal_task_introductions_use_product_identity():
    # Inspect and evaluate the pure constant only; importing legacy main starts
    # data directories and service state and is unnecessary for this check.
    tree = ast.parse(Path('app/main.py').read_text(encoding='utf-8'))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'BASE_SYSTEM' for target in node.targets))
    value = eval(compile(ast.Expression(assignment.value), '<BASE_SYSTEM>', 'eval'),
                 {'IDENTITY_CONTRACT': IDENTITY_CONTRACT, '__builtins__': {}})
    assert value.startswith(IDENTITY_CONTRACT)
    assert 'Never claim an action, research step or code execution that did not actually occur.' in value
    introductions = [node for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
                     and node.values and isinstance(node.values[0], ast.Constant)
                     and str(node.values[0].value).startswith('You are ')]
    assert len(introductions) == 5
    assert all(any(isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name)
                   and part.value.id == 'PRODUCT_NAME' for part in node.values) for node in introductions)


def test_legacy_html_uses_the_current_brand_and_preserves_service_routes():
    tree = ast.parse(Path('app/main.py').read_text(encoding='utf-8'))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'HTML' for target in node.targets))
    html = eval(compile(ast.Expression(assignment.value), '<HTML>', 'eval'),
                {'PRODUCT_NAME': PRODUCT_NAME, '__builtins__': {}})
    assert f'<title>{PRODUCT_NAME}</title>' in html
    assert f'<b>{PRODUCT_NAME}:</b>' in html
    assert f'placeholder="Ask {PRODUCT_NAME}..."' in html
    assert '__PRODUCT_NAME__' not in html and 'PRIME' not in html and 'JARVIS' not in html
    assert "fetch('/api/chat'" in html and "fetch('/api/orchestration/cycle'" in html
