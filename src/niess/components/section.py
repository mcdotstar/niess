from dataclasses import dataclass, fields
from ..utilities import calibration

# TODO Consider whether it would be possible to use any one of:
#      datclass-wizzard: https://dataclass-wizard.readthedocs.io
#      pydantic: https://docs.pydantic.dev
#      dacite: https://github.com/konradhalas/dacite
#      to handle (de)serializing these nested dataclass objects from calibration data.

@dataclass
class Section:

    @classmethod
    def parts(cls):
        """Get the ordered list of components which make up this Section"""
        # Note to self, one _could_ hard code this instead if the
        # dataclasses.fields(cls) trick stops working at some point
        # but the _order_ of the tuple returned by dataclasses.fields(Type) is
        # (currently) guaranteed to be the same as the order of definition above
        return [field.name for field in fields(cls)]

    @classmethod
    def types(cls):
        """Get the ordered list of component types which make up this Section"""
        return [field.type for field in fields(cls)]

    @classmethod
    def items(cls):
        """Get the ordered list of component names and types which make up this Section"""
        return [(field.name, field.type) for field in fields(cls)]

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

        values = [T.from_calibration(named_par(n)) for n, T in cls.items()]
        return cls(*values)