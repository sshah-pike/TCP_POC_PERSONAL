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


ELIGIBLE, NOT_ELIGIBLE, UNDETERMINED = "ELIGIBLE", "NOT_ELIGIBLE", "UNDETERMINED"


def evaluate_eligibility(pack, ta_id, facts):
    """Check one TA's eligibility conditions against facts (registry field -> value).

    A SOURCED condition evaluates to True, False or None (a fact is missing). A SOURCE_REVIEW_REQUIRED or UNKNOWN
    condition is None and adds its SME question. Conditions with the same any_group are OR'd. Any False gives
    NOT_ELIGIBLE; otherwise any None gives UNDETERMINED; otherwise ELIGIBLE.
    """
    conds = [c for c in pack.records("eligibility_condition") if c.ta_id == ta_id]
    rows, questions = [], []
    for c in conds:
        if c.status == Status.SOURCED: v = eval_expr(c.expr, facts)
        else: v = None; questions.append({"condition_id": c.id, "status": c.status.value, "question": c.sme_question})
        rows.append({"condition_id": c.id, "any_group": c.any_group, "result": v})
    units = {}
    for r in rows: units.setdefault(r["any_group"] or r["condition_id"], []).append(r["result"])
    vals = [True if True in v else None if None in v else False for v in units.values()]
    result = NOT_ELIGIBLE if False in vals else UNDETERMINED if None in vals else ELIGIBLE
    failed = [k for k, v in units.items() if True not in v and None not in v]
    return {"ta_id": ta_id, "result": result, "conditions": rows, "failed": failed,
            "questions": questions if result == UNDETERMINED else []}


def screen_tas(pack, facts):
    """Eligibility of every TA in the pack. NO_TA_MATCH when none is ELIGIBLE or UNDETERMINED (D-60)."""
    per_ta = {t.id: evaluate_eligibility(pack, t.id, facts) for t in pack.records("ta")}
    live = [k for k, v in per_ta.items() if v["result"] != NOT_ELIGIBLE]
    return {"per_ta": per_ta, "eligible": [k for k, v in per_ta.items() if v["result"] == ELIGIBLE],
            "undetermined": [k for k, v in per_ta.items() if v["result"] == UNDETERMINED],
            "decision": "NO_TA_MATCH" if not live else None}


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
