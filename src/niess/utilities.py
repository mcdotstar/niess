from scipp import Variable
from mccode_antlr.common.parameters import InstrumentParameter


def is_type(x, t, name):
    if not isinstance(x, t):
        raise RuntimeError(f"{name} must be a {t}")


def has_compatible_unit(x: Variable, unit):
    from scipp import UnitError
    try:
        x.to(unit=unit, copy=False)
    except UnitError:
        return False
    return True


def is_scalar(x: Variable):
    from scipp import DimensionError
    try:
        y = x.value
    except DimensionError:
        return False
    return True


def variable_value_or_parameter(value: Variable | InstrumentParameter, unit: str):
    if isinstance(value, Variable):
        return value.to(unit=unit).value
    return value