"""Recover instrument-scope variables for constant folding.

``moreniius`` did this by constructing a whole ``CTargetVisitor`` and reading its
``instrument_uservars``. That is both unnecessary and wrong: ``instrument_uservars``
is populated from the instrument's USERVARS blocks (``Instr.user``), never from its
DECLARE blocks (``Instr.declare``), so DECLARE'd variables never reached the folding
dictionary and any component parameter referencing one degraded to a bare string.

mccode-antlr exposes the C-declaration parser directly, so parse ``Instr.declare``
and evaluate it against ``Instr.initialize``. USERVARS are deliberately excluded:
they are per-particle values, so they have no place in instrument-scope folding.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def declared_variables(instr) -> dict:
    """Map DECLARE'd instrument variable names to their folded ``Expr`` values."""
    from mccode_antlr.translators.c_listener import (
        extract_c_declared_expressions,
        evaluate_c_defined_expressions,
    )

    block = '\n'.join(raw.source for raw in instr.declare)
    if not block.strip():
        return {}

    try:
        declarations = extract_c_declared_expressions(block)
    except Exception as error:
        logger.warning(f'Failed to parse DECLARE block of {instr.name}: {error}')
        return {}

    variables = {declarator.name: expr for declarator, expr in declarations.items()}

    initialize = '\n'.join(raw.source for raw in instr.initialize)
    if not initialize.strip():
        return variables

    try:
        return evaluate_c_defined_expressions(variables, initialize)
    except Exception as error:
        # An INITIALIZE block that the C expression evaluator cannot digest (pointer
        # arithmetic, unresolved %include, ...) is not fatal: fall back on the values
        # from the DECLARE statements themselves.
        logger.warning(
            f'Failed to evaluate INITIALIZE block of {instr.name}: {error}. '
            'Using DECLARE-statement values only.'
        )
        return variables


def symbol_table(instr) -> dict:
    """Every instrument-scope name a placement or parameter might refer to.

    Instrument parameters first, then DECLARE'd variables, which may be defined in terms
    of the parameters and so must win where both carry the same name.

    The values are the parameters' *defaults*. A `.instr` whose geometry is driven by a
    run-time parameter -- `AT (0, 0, GUI_start)` -- therefore folds to where that
    parameter's default puts it. That is a real loss and the reason `niess.scaffold.emit`
    writes the folded names back out as named Python constants rather than as bare
    numbers: the number is the calibration, the name is the structure the author meant,
    and only one of the two can be recovered automatically.
    """
    known = {parameter.name: parameter.value for parameter in instr.parameters}
    known.update(declared_variables(instr))
    return known


def folder(instr):
    """A callable turning one `Expr` from `instr` into a number.

    Raises `ValueError` naming the expression and what it still depends on, rather than
    returning a wrong number -- a silently mis-placed component is the failure mode this
    whole tool is trying not to have.
    """
    from mccode_antlr.common import Expr

    known = symbol_table(instr)

    def fold(expr, what: str = ''):
        if not isinstance(expr, Expr):
            return float(expr)
        reduced = expr if expr.is_constant else expr.evaluate(known)
        if not reduced.is_constant:
            where = f' for {what}' if what else ''
            raise ValueError(
                f'{expr}{where} does not reduce to a number; it is {reduced}. '
                f'Known symbols: {sorted(known)}'
            )
        return float(reduced.value)

    return fold
