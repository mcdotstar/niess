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
    if held := a.instrument.get_parameter(par.name) and held != par:
        msg = f"Parameter {par.name} already defined"
        if held.value is not None:
            msg += f" with value {held.value}"
        if held.unit is not None:
            msg += f" {held.unit}"
        raise RuntimeError(msg)
    else:
        a.instrument.add_parameter(par)


