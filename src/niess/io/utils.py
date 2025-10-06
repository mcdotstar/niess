from typing import Any, Type
import msgspec
import numpy as np

from niess.bifrost import Tank as BIFROSTTank, Primary as BIFROSTPrimary

from niess.components import (
    DirectSecondary,
    IndirectSecondary,
    IdealCrystal,
    Crystal,
    Wire,
    DiscreteWire,
    DiscreteTube,
    He3Tube,
    Aperture,
    Jaw,
    Slit,
    Chopper,
    DiscChopper,
    FermiChopper,
    Collimator,
    SollerCollimator,
    RadialCollimator,
    Component,
    Attenuator,
    Filter,
    OrderedFilter,
    Guide,
    EllipticGuide,
    TaperedGuide,
    StraightGuide,
    StraightGuides,
    TaperedGuides,
    Moderator,
    FissionChamber,
    He3Monitor,
    BeamCurrentMonitor,
    GEM2D,
    ESSource,
    Section,
)

from .scipp import (
    SCIPP_MODEL_DECODE, SCIPP_MODEL_ENCODE, ScippModel, from_scipp_model,
    SCIPP_TO_DICT, DICT_TO_SCIPP
)
from .mccode import (
    MCCODE_MODEL_ENCODE, MCCODE_MODEL_DECODE, McCodeModel
)

MODEL_ENCODE = {
    BIFROSTTank: 'BIFROST Tank',
    BIFROSTPrimary: 'BIFROST Primary',
    DirectSecondary: 'DirectSecondary',
    IndirectSecondary: 'IndirectSecondary',
    IdealCrystal: 'IdealCrystal',
    Crystal: 'Crystal',
    Wire: 'Wire',
    DiscreteWire: 'DiscreteWire',
    DiscreteTube: 'DiscreteTube',
    He3Tube: 'He3Tube',
    Aperture: 'Aperture',
    Jaw: 'Jaw',
    Slit: 'Slit',
    Chopper: 'Chopper',
    DiscChopper: 'DiscChopper',
    FermiChopper: 'FermiChopper',
    Collimator: 'Collimator',
    SollerCollimator: 'SollerCollimator',
    RadialCollimator: 'RadialCollimator',
    Component: 'Component',
    Attenuator: 'Attenuator',
    Filter: 'Filter',
    OrderedFilter: 'OrderedFilter',
    Guide: 'Guide',
    EllipticGuide: 'EllipticGuide',
    TaperedGuide: 'TaperedGuide',
    StraightGuide: 'StraightGuide',
    StraightGuides: 'StraightGuides',
    TaperedGuides: 'TaperedGuides',
    Moderator: 'Moderator',
    FissionChamber: 'FissionChamber',
    He3Monitor: 'He3Monitor',
    BeamCurrentMonitor: 'BeamCurrentMonitor',
    GEM2D: 'GEM2D',
    ESSource: 'ESSource',
    Section: 'Section',
}
MODEL_DECODE = {v: k for k, v in MODEL_ENCODE.items()}


class Model(msgspec.Struct):
    name: str
    obj: msgspec.Raw

    @classmethod
    def from_value(cls, obj: Any, encoder=None):
        if encoder is None:
            raise ValueError("An encoder must be provided")
        obj_type = type(obj)
        if obj_type in SCIPP_TO_DICT:
            model_type = SCIPP_MODEL_ENCODE[obj_type]
            obj = SCIPP_TO_DICT[obj_type](obj)
        elif obj_type in MCCODE_MODEL_ENCODE:
            model_type = MCCODE_MODEL_ENCODE[obj_type]
            if hasattr(obj, 'to_dict'):
                obj = obj.to_dict()
        else:
            model_type = MODEL_ENCODE[obj_type]
            if hasattr(obj, 'to_dict'):
                obj = obj.to_dict()
        return cls(model_type, msgspec.Raw(encoder.encode(obj)))


def to_model(model_encoder, obj):
    return Model(model_encoder, obj)


def traverse_decoded(a):
    if isinstance(a, dict):
        return traverse_decoded_dict(a)
    return traverse_decoded_one(a)


def traverse_decoded_dict(d: dict):
    """Convert special dicts based on specified conversion routines or
    traverse through the provided standard dict"""
    if 'name' in d and 'obj' in d and len(d) == 2:
        # one of the models:
        if d['name'] in DICT_TO_SCIPP:
            return DICT_TO_SCIPP[d['name']](d['obj'])
        print(f"{d['name']} should be handled")
    # if 'name' in d and 'obj' in d and d['name'] in DICT_TO_MCCODE:
    #     return DICT_TO_MCCODE[d['name']](d['obj'])
    for k, v in d.items():
        d[k] = traverse_decoded(v)
    return d


def traverse_decoded_one(a):
    if isinstance(a, dict):
        return traverse_decoded_dict(a)
    elif isinstance(a, list):
        return [traverse_decoded(x) for x in a]
    elif isinstance(a, tuple):
        return tuple(traverse_decoded(x) for x in a)
    return a


def from_model(model_decoder, model):
    if model.name in MODEL_DECODE:
        data = model_decoder.decode(model.obj)
        if isinstance(data, dict):
            data = traverse_decoded_dict(data)
            return MODEL_DECODE[model.name].from_dict(data)
        return data
    elif model.name in SCIPP_MODEL_DECODE:
        data = model_decoder.decode(model.obj)
        if isinstance(data, dict):
            return DICT_TO_SCIPP[model.name](data)
        return data
    elif model.name in MCCODE_MODEL_DECODE:
        data = model_decoder.decode(model.obj)
        if isinstance(data, dict):
            return MCCODE_MODEL_DECODE[model.name].from_dict(data)
        return data
    raise ValueError(f"Model {model.name} is not supported")


def encode_hook(encoder):
    def hook(obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif type(obj) in SCIPP_MODEL_ENCODE:
            return ScippModel.from_value(obj, encoder)
        raise TypeError(f"Object of type {type(obj)} is not supported")
    return hook


def decode_hook(scipp_model_decoder):
    def hook(typ: Type, obj: Any):
        if typ is ScippModel:
            return from_scipp_model(scipp_model_decoder, obj)
        # A data type that's been encoded as a ScippModel doesn't know it?
        if typ in SCIPP_MODEL_ENCODE and isinstance(obj, dict) and 'obj' in obj:
            return DICT_TO_SCIPP[SCIPP_MODEL_ENCODE[typ]](obj['obj'])
        raise TypeError(f"Object of type {type(obj)} is not supported")
    return hook


def schema_hook(typ):
    from .scipp import SCIPP_JSON_SCHEMA
    if typ in SCIPP_JSON_SCHEMA:
        return SCIPP_JSON_SCHEMA[typ]()
    raise TypeError(f"Object of type {typ} is not supported")
