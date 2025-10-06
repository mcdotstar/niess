# from dataclasses import dataclass, fields
import msgspec
from typing import ClassVar, Type
from ..utilities import calibration

# TODO Consider whether it would be possible to use any one of:
#      datclass-wizzard: https://dataclass-wizard.readthedocs.io
#      pydantic: https://docs.pydantic.dev
#      dacite: https://github.com/konradhalas/dacite
#      to handle (de)serializing these nested dataclass objects from calibration data.

# @dataclass
class Section(msgspec.Struct, tag=True):
    __struct_field_types__ = ClassVar[dict[str, Type]]

    @classmethod
    def parts(cls):
        """Get the ordered list of components which make up this Section"""
        # Note to self, one _could_ hard code this instead if the
        # dataclasses.fields(cls) trick stops working at some point
        # but the _order_ of the tuple returned by dataclasses.fields(Type) is
        # (currently) guaranteed to be the same as the order of definition above
        return cls.__struct_fields__

    @classmethod
    def types(cls):
        """Get the ordered list of component types which make up this Section"""
        return [cls.__struct_field_types__[field] for field in cls.__struct_fields__]

    @classmethod
    def items(cls):
        """Get the ordered list of component names and types which make up this Section"""
        return [(field, cls.__struct_field_types__[field]) for field in cls.__struct_fields__]

    def to_mccode(self, *args, **kwargs):
        for part in self.parts():
            getattr(self, part).to_mccode(*args, **kwargs)

    @classmethod
    @calibration
    def from_calibration(cls, parameters: dict):
        for part in cls.parts():
            assert part in parameters

        def named_par(name):
            if 'name' not in parameters[name]:
                parameters[name]['name'] = name
            return parameters[name]

        def to_type(name):
            typ = cls.__struct_field_types__[name]
            if isinstance(parameters[name], typ):
                return parameters[name]
            return typ.from_calibration(named_par(name))

        return cls(*[to_type(n) for n in cls.parts()])

    def to_dict(self):
        return {f: getattr(self, f) for f in self.__struct_fields__}

    @classmethod
    def from_dict(cls, d):
        # TODO make a function to recurse through a dictionary and ensure
        #      scipp.Variable and mccode_antlr.? are converted
        return cls.from_calibration(d)