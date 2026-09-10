"""Bounded, pure capabilities; feasibility never grants action authority.

Only complete matching contracts are accepted. There is no eval, I/O, plugin
loading or inferred permission. Unsupported/malformed exact requests fail
closed instead of paying a model to approximate their answer.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from fractions import Fraction


CAPABILITIES = ("arithmetic.v1", "sha256.utf8.v1", "schema.validation.v1", "agent.registry.lookup.v1")
POLICY_VERSION = "deterministic-feasibility.v1"


@dataclass(frozen=True)
class Feasibility:
    resolution_path: str
    reason_code: str
    capability: str | None = None
    result: str | None = None
    policy_version: str = POLICY_VERSION

    def as_dict(self):
        return asdict(self)


def _arithmetic(expression: str) -> str:
    if len(expression) > 1024 or not re.fullmatch(r"[0-9.()+*/\s-]+", expression):
        raise ValueError("outside arithmetic contract")
    tree = ast.parse(expression.strip(), mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise ValueError("expression too complex")

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = Fraction(ast.get_source_segment(expression.strip(), node))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): value = left + right
            elif isinstance(node.op, ast.Sub): value = left - right
            elif isinstance(node.op, ast.Mult): value = left * right
            else: value = left / right
        else:
            raise ValueError("unsupported operator")
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > 4096:
            raise ValueError("result too large")
        return value

    return str(visit(tree.body))


def assess(prompt: str) -> Feasibility:
    text = prompt.strip()
    schema = re.fullmatch(r"validate schema ([a-z0-9-]+):\s*(.*)", text, re.I | re.S)
    if schema:
        from .generated.portfolio_contracts import validate_contract
        try:
            if len(prompt) > 120000:
                raise ValueError("input limit")
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError("duplicate JSON key")
                    result[key] = value
                return result
            def invalid_constant(value):
                raise ValueError("non-finite JSON")
            def finite_float(value):
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("non-finite JSON")
                return number
            value = json.loads(schema.group(2), object_pairs_hook=pairs,
                               parse_constant=invalid_constant, parse_float=finite_float)
            result = validate_contract(schema.group(1).lower(), value)
        except (ValueError, RecursionError, OverflowError):
            return Feasibility("reject", "DETERMINISTIC_CONTRACT_INVALID", "schema.validation.v1")
        return Feasibility("deterministic", "DETERMINISTIC_CONTRACT_SATISFIED", "schema.validation.v1",
                           json.dumps(result, sort_keys=True))
    lookup = re.fullmatch(r"lookup agent ([a-z0-9-]+)", text, re.I)
    if lookup:
        from .agent_registry import agent_record, RegistryError
        try:
            record = agent_record(lookup.group(1))
            result = {key: record[key] for key in ("agent_id", "name", "role", "status")}
        except (RegistryError, KeyError, ValueError):
            return Feasibility("reject", "REGISTRY_ENTRY_UNAVAILABLE", "agent.registry.lookup.v1")
        return Feasibility("deterministic", "DETERMINISTIC_CONTRACT_SATISFIED", "agent.registry.lookup.v1",
                           json.dumps(result, sort_keys=True))
    arithmetic = re.fullmatch(r"(?:calculate|compute|what is)\s+(.+?)[?]?", text, re.I | re.S)
    bare = re.fullmatch(r"[0-9.()+*/\s-]+", text)
    # 'Compute a strategy' is not an arithmetic contract. A leading numeric
    # expression with extra instructions is rejected rather than truncated.
    expression = arithmetic.group(1).strip() if arithmetic else text
    if bare or (arithmetic and re.match(r"[0-9.(+\-]", expression)):
        try:
            result = _arithmetic(expression)
        except (ValueError, SyntaxError, ZeroDivisionError, RecursionError, OverflowError):
            return Feasibility("reject", "DETERMINISTIC_CONTRACT_INVALID", "arithmetic.v1")
        return Feasibility("deterministic", "DETERMINISTIC_CONTRACT_SATISFIED", "arithmetic.v1", result)
    # Exact text after the delimiter is the UTF-8 payload, including whitespace.
    match = re.match(r"\Asha256 text: ?", prompt, re.I)
    if match:
        if len(prompt) > 120000:
            return Feasibility("reject", "DETERMINISTIC_INPUT_LIMIT", "sha256.utf8.v1")
        result = hashlib.sha256(prompt[match.end():].encode("utf-8")).hexdigest()
        return Feasibility("deterministic", "DETERMINISTIC_CONTRACT_SATISFIED", "sha256.utf8.v1", result)
    return Feasibility("local_inference", "NO_REGISTERED_DETERMINISTIC_CONTRACT")
