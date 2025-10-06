from typing import Any, Type
import msgspec
from scipp import Variable, DType


SCIPP_MODEL_ENCODE = {
    Variable: 'scipp.Variable'
}
SCIPP_MODEL_DECODE = {v: k for k, v in SCIPP_MODEL_ENCODE.items()}

def variable_to_dict(v: Variable) -> dict[str, Any]:
    d = {'unit': str(v.unit), 'dtype': str(v.dtype)}
    def tolist(x):
        if d['dtype'] == 'string' and v.size == 1:
            return x
        if hasattr(x, 'tolist'):
            return x.tolist()
        return x

    if v.size == 1:
        d['value'] = tolist(v.value)
        if v.variance is not None:
            d['variance'] = tolist(v.variance)
    else:
        d['values'] = tolist(v.values)
        d['dims'] = list(v.dims)
        if v.variances is not None:
            d['variances'] = tolist(v.variances)
    return d

def variable_json_schema():
    schema = {
        "$defs": {
            "nd_array": {
                "type": "array",
                "items": {"type": ["string", "integer", "number", {"$ref": "#/$defs/nd_array"}]},
                "minItems": 1
            }
        },
        'type': 'object',
        "title": "Scipp Variable",
        "description": "A scalar or array variable in scipp",
        "properties": {
            'unit': {"type": "string"},
            'dtype': {"type": "string"},
            "value": {"type": "number"},
            "variance": {"type": "number"},
            "values": {"type": {"$ref": "#/$defs/nd_array"}},
            "variances": {"type": {"$ref": "#/$defs/nd_array"}},
            "dims": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["unit", "dtype", {"oneOf": ["value", "values"]}]
    }
    return schema


def dict_to_variable(d: dict) -> Variable:
    from scipp import array, scalar
    if isinstance(dtype := d['dtype'], str) and hasattr(DType, dtype):
        d['dtype'] = getattr(DType, dtype)
    if 'values' in d:
        return array(**d)
    else:
        return scalar(**d)


SCIPP_TO_DICT = {
    Variable: variable_to_dict,
}
DICT_TO_SCIPP = {
    'scipp.Variable': dict_to_variable,
}

SCIPP_JSON_SCHEMA = {Variable: variable_json_schema}


class ScippModel(msgspec.Struct):
    name: str
    obj: msgspec.Raw

    @classmethod
    def from_value(cls, obj: Any, encoder=None):
        if encoder is None:
            raise ValueError("An encoder must be provided")
        model_type = SCIPP_MODEL_ENCODE[type(obj)]
        if 'scipp.Variable' == model_type:
            obj = variable_to_dict(obj)
        return cls(model_type, msgspec.Raw(encoder.encode(obj)))


def to_scipp_model(scipp_model_encoder, obj):
    return ScippModel(scipp_model_encoder, obj)


def from_scipp_model(scipp_model_decoder, msg: ScippModel):
    if msg.name in SCIPP_MODEL_DECODE:
        return decode_scipp_model(scipp_model_decoder.decode(msg.obj))
    raise TypeError(f"{msg.name} is not a valid scipp model")

def decode_scipp_model(data: dict):
    return dict_to_variable(data)