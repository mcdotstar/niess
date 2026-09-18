"""Helpers for driving an ``mccode_antlr`` Assembler.

The small things every ``to_mccode`` needs and none of them should spell out twice:
declaring a run-time parameter without tripping over a repeated definition, finding the
instrument's own name from inside a nested section, adding a component registry.

Deliberately the bottom of the stack. Nothing here knows what a niess object is, which is
what lets `niess.components` and `niess.bifrost` use it without either of them being
below the McStas *target* -- which sits above `niess.dispatch` and is a different layer
entirely. See `niess.mccode`.
"""
from __future__ import annotations

from mccode_antlr.assembler import Assembler
from mccode_antlr.common import InstrumentParameter


def ensure_user_var(a: Assembler, dtype: str, name: str, description: str):
    """Ensure that particle struct parameter is declared"""
    a.ensure_user_var(f'{dtype} {name}; // {description}')


def declare_array(instrument: Assembler, element_type: str, name: str, description: str, values):
    instrument.declare_array(element_type, name, values)


def ensure_parameter(a: Assembler, data_type: str, name: str, description: str):
    """Ensure that a parameter is declared in the instrument"""
    a.parameter(f'{data_type} {name}; // {description}', ignore_repeated=True)


def ensure_runtime_line(a: Assembler, line: str):
    """Ensure that a runtime-defined parameter is declared in the instrument

        Utilizes the parser to define an `InstrumentParameter` object, which can have
        a string representation like:
            parameter_type parameter_name/"parameter unit" = default_value; // comment
        which gets truncated at the ';' (or '//' if ';' is missing) such that the comment
        is dropped.

        Each of parameter_type, parameter_unit, default_value and comment are optional,
        such that
            parameter_name
        is the minimally valid definition.
        If missing, `parameter_type` is equivalent to specifying 'double'.
        The default value depends on the type, but is typically 0.

        Repeated definitions of the same parameter are ignored, but inconsistent
        default, type, or units will raise an error.
    """
    return ensure_runtime_parameter(a, InstrumentParameter.parse(line))


def ensure_runtime_parameter(a: Assembler, par: InstrumentParameter):
    """Ensure that a runtime-defined parameter is declared in the instrument

    Repeated definitions of the same parameter are ignored, but inconsistent
    default, type, or units will raise an error.
    """
    held = a.instrument.get_parameter(par.name)
    if held is None:
        a.instrument.add_parameter(par)
        return
    if held != par:
        msg = f"Parameter {par.name} already defined"
        if held.value is not None:
            msg += f" with value {held.value}"
        if held.unit is not None:
            msg += f" {held.unit}"
        raise RuntimeError(msg)


def root_assembler(a: Assembler) -> Assembler:
    """The outermost Assembler of a (possibly nested) assembly.

    ``Assembler.included()`` builds a section as a child assembler whose own name is
    the section's, so anything naming itself after ``assembler.name`` inside a section
    picks up the section name rather than the instrument's. Walk to the root when the
    instrument as a whole is what is meant.
    """
    while getattr(a, 'parent', None) is not None:
        a = a.parent
    return a


def instrument_name(a: Assembler) -> str:
    """The name of the instrument being assembled, from anywhere in the hierarchy."""
    return root_assembler(a).name


def ensure_registry(a: Assembler, specification: str):
    """Ensure that a register-defined parameter is declared in the instrument

    Parameters
    ----------
    a : Assembler
    specification : str
        Any of the mccode_antlr.reader.registry supported formats,
        1. ``{resolvable folder path}``
        2. ``{name} {resolvable folder path}``
        3. ``{name} {resolvable url} {resolvable file path}``
        4. ``{name} {resolvable url} {version} {registry file name}``
        5. ``git+{url}@{version}`` or ``git+{url}@{version}#{registry-file}``
        6. ``{owner}/{repo}@{version}`` or ``{owner}/{repo}@{version}#{registry-file}``
    """
    from mccode_antlr.reader.registry import registry_from_specification as rfs
    reg = rfs(specification)
    if not reg:
        msg = f"Unable to construct registry from {specification}"
        if not 'http' in specification and '/' in specification and not '@' in specification:
            msg += " missing @{tag|branch|commit} in GitHub Actions style specification"
        raise RuntimeError(msg)
    if not reg in a.instrument.registries:
        a.instrument.registries += (reg,)
