"""Bounded, pure capabilities; feasibility never grants action authority.

Only complete matching contracts are accepted. There is no eval, I/O, plugin
loading or inferred permission. Unsupported/malformed exact requests fail
closed instead of paying a model to approximate their answer.
"""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import asdict, dataclass
from fractions import Fraction


CAPABILITIES = ("arithmetic.v1", "sha256.utf8.v1")
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
