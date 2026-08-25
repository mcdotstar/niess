"""Decide whether a component parameter is a literal or a runtime link.

A McCode component parameter is an ``Expr``. If it folds to a compile-time
constant -- possibly only after substituting DECLARE'd instrument variables --
it becomes a literal value in the NeXus file. If it depends on an instrument
parameter, whose value is only known at run time, it instead becomes a link to
the ``NXlog`` where that parameter's value is published (by an f144 module,
assumed to be configured elsewhere).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..nodes import dataset, group
from ..streams import link_specifier, linked_nxlog


@dataclass(frozen=True)
class Literal:
    """A value known at translation time."""
    value: Any


@dataclass(frozen=True)
class LinkedLog:
    """The parameter *is* an instrument parameter: link its whole NXlog."""
    parameter: str
    source: str


@dataclass(frozen=True)
class LinkedExpression:
    """The parameter is an expression over one or more instrument parameters."""
    expression: str
    sources: dict[str, str] = field(default_factory=dict)


Resolved = Literal | LinkedLog | LinkedExpression


def resolve(expr, declared: dict, parameters, nxlog_root: str) -> Resolved:
    """Fold ``expr`` to a literal, or describe the link(s) it needs."""
    from mccode_antlr.common import Expr

    if not isinstance(expr, Expr):
        return Literal(expr)

    if expr.is_constant:
        return Literal(expr.value)

    evaluated = expr.evaluate(declared)
    if evaluated.is_constant:
        return Literal(evaluated.value)

    dependencies = [par.name for par in parameters if evaluated.depends_on(par.name)]

    if len(dependencies) == 1 and str(expr) == str(dependencies[0]):
        return LinkedLog(dependencies[0], f'{nxlog_root}/{dependencies[0]}')

    if dependencies:
        return LinkedExpression(
            str(expr),
            {name: f'{nxlog_root}/{name}' for name in dependencies},
        )

    # Depends on something that is neither a DECLARE'd variable nor an instrument
    # parameter -- keep the expression text so the information is not simply lost.
    return Literal(str(expr))


def is_literal(resolved: Resolved) -> bool:
    return isinstance(resolved, Literal)


def literal_value(resolved: Resolved, default=None):
    return resolved.value if isinstance(resolved, Literal) else default


def parameter_node(name: str, resolved: Resolved, attrs: dict | None = None) -> dict:
    """Build the node a resolved parameter needs: a dataset, or a linking group."""
    if isinstance(resolved, Literal):
        return dataset(name, resolved.value, attrs=attrs)
    if isinstance(resolved, LinkedLog):
        return linked_nxlog(name, resolved.source, attrs=attrs)
    if isinstance(resolved, LinkedExpression):
        children = [dataset('expression', resolved.expression)]
        children.extend(
            link_specifier(parameter, source)
            for parameter, source in resolved.sources.items()
        )
        return group(name, 'NXcollection', children=children, attrs=attrs)
    raise TypeError(f'Not a resolved parameter: {resolved!r}')
