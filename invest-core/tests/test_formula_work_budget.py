"""Arithmetic work, not serialized formula length, owns formula resources."""
from __future__ import annotations

import ast
import math

import pytest

import invest_contracts as arithmetic
ENTRY = "evaluate_formula"


def evaluate(formula, inputs, *, work_budget=None):
    entry = getattr(arithmetic, ENTRY)
    if work_budget is None:
        return entry(formula, inputs)
    return entry(formula, inputs, work_budget=work_budget)


def budget(limit=None):
    return arithmetic.FormulaWorkBudget(max_work_units=limit)


def test_equivalent_whitespace_does_not_change_validity():
    short = "x0+0"
    expanded = "x0" + " " * 501 + "+0"
    assert len(expanded) > 500
    assert ast.dump(ast.parse(short, mode="eval")) == ast.dump(ast.parse(expanded, mode="eval"))
    assert evaluate(short, [3.5]) == evaluate(expanded, [3.5]) == 3.5


def test_true_long_formula_is_not_only_a_whitespace_exception():
    formula = "+".join(["x0"] * 350)
    assert len(formula) > 500
    assert math.isclose(evaluate(formula, [0.3]), 350 * 0.3)


def test_deep_unary_evaluation_does_not_use_python_recursion():
    assert evaluate("-" * 600 + "x0", [7]) == 7


def test_one_explicit_work_account_can_span_multiple_formulas():
    account = budget(10)
    assert evaluate("x0", [2], work_budget=account) == 2
    used = account.work_units
    assert used > 0
    with pytest.raises(ValueError, match="work budget"):
        evaluate("x0+x0", [2], work_budget=account)
    assert account.work_units > used


def test_parse_work_is_reserved_before_parser(monkeypatch):
    account = budget(1)
    called = []
    original = arithmetic.ast.parse
    def observed(*args, **kwargs):
        called.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(arithmetic.ast, "parse", observed)
    with pytest.raises(ValueError, match="work budget"):
        evaluate("x0+0", [1], work_budget=account)
    assert called == []


def test_unlimited_account_is_observation_without_a_hidden_ceiling():
    account = budget()
    assert evaluate("x0" + " " * 12000 + "+0", [4], work_budget=account) == 4
    assert account.work_units > 12000


@pytest.mark.parametrize("formula,values", [
    ("x1", [1]),
    ("x0/0", [1]),
    ("1e308**11", []),
    ("(-1)**0.5", []),
    ("0**-1", []),
    ("__import__('os')", []),
    ("x0[0]", [1]),
    ("x0%2", [1]),
    ("1e309", []),
    ("(", []),
    ("x0", [float("nan")]),
    ("x0", [float("inf")]),
])
def test_invalid_math_and_unsupported_nodes_remain_named_refusals(formula, values):
    with pytest.raises(ValueError):
        evaluate(formula, values)


@pytest.mark.parametrize("formula,values,expected", [
    ("x0*x1+x2", [100, 1.05, 2], 107.0),
    ("x0/(1+x1)**x2", [120, 0.1, 2], 120/1.1**2),
    ("-x0+x1", [10, 20], 10),
    ("x0**0.5", [9], 3),
])
def test_existing_economic_math_is_unchanged(formula, values, expected):
    assert math.isclose(evaluate(formula, values), expected, rel_tol=1e-12)


@pytest.mark.parametrize("formula,values,expected", [
    pytest.param("x0/(1+x1)**x2", [100, 0.1, 15], 100/1.1**15, id="discount-15-years"),
    pytest.param("x0**x1", [1.05, 30], 1.05**30, id="compound-30-years"),
    pytest.param("2**11", [], 2048, id="ordinary-exponent-11"),
])
def test_long_horizon_financial_powers_are_real_arithmetic(formula, values, expected):
    assert math.isclose(evaluate(formula, values), expected, rel_tol=1e-12)
