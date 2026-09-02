import msgspec
from mccode_antlr.common import InstrumentParameter


def mc_dtype(value) -> str:
    if isinstance(value, str):
        return 'string'
    if isinstance(value, int):
        return 'int'
    if isinstance(value, float):
        return 'double'
    raise TypeError


class Motor(msgspec.Struct):
    name: str
    unit: str
    source: str
    topic: str
    default: float | int

    def parameter(self) -> InstrumentParameter:
        rep = f'{self.name}/"{self.unit}"'
        if self.default is not None:
            rep = f'{mc_dtype(self.default)} {rep} = {self.default}'
        return InstrumentParameter.parse(rep)
