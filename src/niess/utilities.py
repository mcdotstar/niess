from __future__ import annotations

from scipp import Variable
from mccode_antlr.common.parameters import InstrumentParameter, Expr


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
    if isinstance(value, InstrumentParameter):
        return value.name
    return value


def serializable(a):
    if isinstance(a, dict):
        return serializable_dict(a)
    return serializable_one(a)


def serializable_dict(data: dict):
    for k, v in data.items():
        data[k] = serializable(v)
    return data


def serializable_one(v):
    if isinstance(v, Variable):
        return serialize_scipp(v)
    elif isinstance(v, InstrumentParameter) or isinstance(v, Expr):
        return serialize_mccode(v)
    elif isinstance(v, dict):
        return serializable_dict(v)
    elif isinstance(v, tuple):
        return tuple(serializable(a) for a in v)
    elif isinstance(v, list):
        return [serializable(a) for a in v]
    return v


def scipp_dtype_to_python(value: Variable):
    from scipp import DType
    dtype = value.dtype
    if dtype == DType.rotation3 or dtype == DType.vector3:
        # these are always floats
        return [float(v) for v in value.value]
    if dtype == DType.float64 or dtype == DType.float32:
        return float(value.value)
    elif dtype == DType.int64 or dtype == DType.int32:
        return int(value.value)
    return value.value


def serialize_scipp(value: Variable):
    """Convert scipp Variable objects to serializable dicts

    Only scalar and array objects used in this module are supported.
    Extending to new types of objects could be achieved.
    """
    from .spatial import __is_vector__, __is_quaternion__
    rep = {}
    if is_scalar(value):
        rep['type'] = 'scipp_scalar'
        rep['value'] = scipp_dtype_to_python(value)
    else:
        rep['type'] = 'scipp_array'
        rep['values'] = [scipp_dtype_to_python(v) for v in value]
        rep['dims'] = value.dims

    rep['dtype'] = str(value.dtype)
    rep['unit'] = str(value.unit)
    return rep


def serialize_mccode(value: InstrumentParameter | Expr):
    if isinstance(value, InstrumentParameter):
        print(f'Requested to make parameter {value} serializable')
        return {'type': 'mccode_instrument_parameter', 'value': str(value)}
    elif isinstance(value, Expr):
        return {'type': 'mccode_expr', 'value': value.value, 'scalar': value.is_scalar, 'dtype': str(value.data_type)}


def dprint(d: dict, n: int = 0):
    """Pretty print a dictionary with indent-depth indicating nesting"""
    pre = ' '*n
    for k, v in d.items():
        if isinstance(v, dict):
            print(f'{pre}{k}:')
            dprint(v, n + 1)
        else:
            print(f'{pre}{k}: {v}')


def compare(a, b, depth: str = None):
    """Compare two dictionaries, list, tuples, or numeric values for equivalency

    Nesting of dictionaries, lists, and tuples supported.
    """
    if depth is None:
        depth = ''
    if not isinstance(a, type(b)):
        return False
    if isinstance(a, dict):
        return compare_dict(a, b, depth=depth)
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(compare(x, y, depth=depth) for x, y in zip(a, b))
    return compare_one(a, b, depth=depth)


def compare_dict(dict1, dict2, depth: str):
    for kappa in dict2:
        if kappa not in dict1:
            return False
    for k, v in dict1.items():
        if k not in dict2:
            return False
        nu = dict2[k]
        return compare(v, nu, depth=f'{depth}/k')


def compare_one(a, b, depth: str):
    """Compare two things which are not dicts, lists, or tuples and are the same type"""
    from numpy import allclose
    if isinstance(a, str):
        return a == b
    return allclose(a, b)


def calibration_input(*args, **kwargs):
    """Allow specifying the calibration parameters as a single positional dict or
    any number of keyword arguments, with the latter taking precedence."""
    if len(args) == 1 and isinstance(args[0], dict):
        params = args[0].copy()
    elif len(args):
        raise ValueError('only one (dict) positional argument or keyword arguments are allowed')
    else:
        params = {}
    params.update(kwargs)
    return params


def calibration(func):
    """A decorator for, e.g. a `@classmethod` decorated Class method which is the
    from_calibration function for the class to handle input collation"""
    def wrapper(*args, **kwargs):
        if len(args) > 1:
             # ensure we have (class, dict) or similar?
            return func(*args[:-1], calibration_input(args[-1], **kwargs))
        return func(calibration_input(*args, **kwargs))
    return wrapper
