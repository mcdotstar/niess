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
