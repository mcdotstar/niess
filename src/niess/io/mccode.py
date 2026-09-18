"""Reading and writing McCode's own objects.

niess translates niess instruments, so nothing here is a translation front-end. What is
here is the other direction: turning an `mccode_antlr` object into something serialisable,
and reading a `.instr` back in so its placements can be *inspected* -- to check a niess
submodule against the hand-written file it replaces, which is what
``docs/examples/verify_translation.py`` does. Converting an instrument niess did not build
is deliberately not supported.
"""
from __future__ import annotations

from pathlib import Path
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


def load_instr(filepath: str | Path):
    """Load an ``Instr`` from a McCode ``.instr`` file or a serialized instrument."""
    filepath = Path(filepath)
    if not filepath.is_file():
        raise ValueError(f'{filepath} does not exist or is not a file')

    suffix = filepath.suffix.lower()
    if suffix == '.instr':
        from mccode_antlr.loader import load_mcstas_instr
        return load_mcstas_instr(filepath)
    if suffix == '.json':
        from mccode_antlr.io.json import load_json
        return load_json(filepath)
    if suffix in ('.msgpack', '.mpk'):
        from mccode_antlr.io.msgpack import load_msgpack
        return load_msgpack(filepath)

    raise ValueError(f'Cannot load an instrument from {filepath.suffix} files')
