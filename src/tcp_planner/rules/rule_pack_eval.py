"""Evaluation of rule-pack conditions and formulas. Holds no values: every number comes from the pack record.

Conditions are three-valued: True, False, or None when a fact they read is missing (UNKNOWN). Formula expressions
are parsed with a whitelist (numbers, the formula's own variables, + - * / ** and unary minus); nothing else runs.
Results are never rounded.
"""
import ast
from tcp_planner.contracts import RulePackError
from tcp_planner.rules.rule_pack_models import All, Any_, Cmp, Not, Status

_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
           ast.Div: lambda a, b: a / b, ast.Pow: lambda a, b: a ** b}


def _parse(expression):
    try: tree = ast.parse(expression, mode="eval")
    except SyntaxError as e: raise ValueError(f"not an expression: {e.msg}")
    for node in ast.walk(tree):
        ok = isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.USub)) \
            or type(node) in _BINOPS \
            or (isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool))
        if not ok: raise ValueError(f"{type(node).__name__} is not allowed")
    return tree.body


def expression_names(expression):
    """Variable names an expression uses. Raises ValueError for anything outside the whitelist."""
    return {n.id for n in ast.walk(_parse(expression)) if isinstance(n, ast.Name)}


def eval_arith(expression, env):
    def ev(n):
        if isinstance(n, ast.Constant): return n.value
        if isinstance(n, ast.Name): return env[n.id]
        if isinstance(n, ast.UnaryOp): return -ev(n.operand)
        return _BINOPS[type(n.op)](ev(n.left), ev(n.right))
    return ev(_parse(expression))


_CMP = {"EQ": lambda a, b: a == b, "NE": lambda a, b: a != b, "LT": lambda a, b: a < b, "LE": lambda a, b: a <= b,
        "GT": lambda a, b: a > b, "GE": lambda a, b: a >= b, "IN": lambda a, b: a in b}


def eval_expr(e, facts):
    """True, False, or None when a needed fact is missing."""
    if isinstance(e, Cmp):
        v = facts.get(e.field)
        return None if v is None else _CMP[e.op](v, e.value)
    if isinstance(e, Not):
        v = eval_expr(e.not_, facts); return None if v is None else not v
    vals = [eval_expr(x, facts) for x in (e.all if isinstance(e, All) else e.any)]
    if isinstance(e, All): return False if False in vals else None if None in vals else True
    return True if True in vals else None if None in vals else False


def evaluate_formula(pack, formula_id, facts):
    """Evaluate a COMPUTE formula for the given facts (registry field -> value).

    Returns {status, value, unit, qualifier, formula_id, expression, inputs, reason, trace}. status is SOURCED with a
    value, SOURCE_REVIEW_REQUIRED when the formula or no case covers the inputs (e.g. 41 to 44 mph for Table 6B-4),
    or UNKNOWN when an input fact is missing. A value is never produced outside the source's stated cases.
    """
    f = pack.get(formula_id)
    if f.role != "COMPUTE":
        raise RulePackError("RULE_PACK_FORMULA_CITED_ONLY", f"{formula_id} is cited only and never computes", {"id": formula_id})
    out = {"formula_id": f.id, "unit": f.result_unit, "qualifier": f.qualifier, "value": None, "expression": None,
           "inputs": {}, "reason": None, "trace": pack.trace(f.id)}

    def done(status, reason=None, **kw): return {**out, "status": status, "reason": reason, **kw}

    if f.status != Status.SOURCED: return done(f.status.value, f"{f.id} is {f.status.value}")
    env = {}
    for sym, bind in f.variables.items():
        if pack.by_id.get(bind) is not None and getattr(pack.by_id[bind], "cases", None) is not None:
            sub = evaluate_formula(pack, bind, facts)
            if sub["status"] != Status.SOURCED.value:
                return done(sub["status"], f"{sym} from {bind}: {sub['reason']}", inputs={sym: sub})
            env[sym] = sub["value"]; out["inputs"][sym] = sub
        else:
            if facts.get(bind) is None: return done(Status.UNKNOWN.value, f"input {bind} is missing")
            env[sym] = facts[bind]; out["inputs"][sym] = {"field": bind, "value": facts[bind]}
    results = [(c, None if c.when is None else eval_expr(c.when, facts)) for c in f.cases]
    if any(r is None and c.when is not None for c, r in results):
        return done(Status.UNKNOWN.value, "a case condition reads a missing fact")
    hits = [c for c, r in results if c.when is None or r is True]
    if not hits: return done(Status.SOURCE_REVIEW_REQUIRED.value, f"no case of {f.id} covers the inputs")
    if len(hits) > 1: raise RulePackError("RULE_PACK_FORMULA_AMBIGUOUS", f"{f.id}: more than one case applies", {"id": f.id})
    return done(Status.SOURCED.value, value=eval_arith(hits[0].expression, env), expression=hits[0].expression)
