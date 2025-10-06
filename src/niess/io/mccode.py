from typing import Any, Type
import msgspec

from mccode_antlr.io.utils import MODEL_ENC

MCCODE_MODEL_ENCODE = {k: f'mccode.{v}' for k, v in MODEL_ENC.items()}
MCCODE_MODEL_DECODE = {v: k for k, v in MCCODE_MODEL_ENCODE.items()}


class McCodeModel(msgspec.Struct):
    name: str
    obj: msgspec.Raw

    @classmethod
    def from_value(cls, obj: Any, encoder=None):
        if encoder is None:
            raise ValueError("And encoder must be provided")
        model_type = MCCODE_MODEL_ENCODE[type(obj)]
        if model_type in MCCODE_MODEL_DECODE and hasattr(obj, 'to_dict'):
            obj = obj.to_dict()
        return cls(model_type, msgspec.Raw(encoder.encode(obj)))


def reconstitute_instrument_parameter(a: Any, others: tuple[Type,...]):
    from mccode_antlr.common import InstrumentParameter
    if a is None or isinstance(a, InstrumentParameter) or any(isinstance(a, x) for x in others):
        return a
    if isinstance(a, str):
        return InstrumentParameter.parse(a)
    if isinstance(a, dict):
        return InstrumentParameter.from_dict(a)
    raise ValueError(f"Unknown relationship of type {type(a)} to InstrumentParameter")