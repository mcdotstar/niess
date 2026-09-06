import msgspec
from mccode_antlr.common import InstrumentParameter


def unquote(unit: str | None) -> str:
    """A McCode unit as a unit.

    ``InstrumentParameter.parse('jaw_l/"m" = -0.015').unit`` is the four characters
    ``"m"``, quotes included, because that is how a McCode instrument declares one. A
    NeXus ``value_units`` is ``m``. Written down once, here, rather than at each place
    that reads a parameter's unit -- the file that reached the filewriter carrying
    ``"\"m\""`` did so through one of them.
    """
    if unit is None:
        return ''
    return unit.strip().strip('"').strip("'")


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
    #: The EPICS positioner this axis really is, when somebody has wired one up.
    pv_root: str | None = None

    def parameter(self) -> InstrumentParameter:
        rep = f'{self.name}/"{self.unit}"'
        if self.default is not None:
            rep = f'{mc_dtype(self.default)} {rep} = {self.default}'
        return InstrumentParameter.parse(rep)

    def to_log(self, name: str | None = None, attrs: dict[str, str] | None = None):
        """Produce an NXlog group for this f144 streammed motor position"""
        from ..nexus.streams import motor_group
        attrs = (attrs or {}) | {'units': self.unit}
        return motor_group(
            name=self.name if name is None else name,
            source=self.source,
            topic=self.topic,
            attrs=attrs,
            default=self.default,
        )

    def to_positioner(self, name: str | None = None, depends_on: str | None = None):
        """Produce an NXpositioner group for this f144 streammed motor position"""
        from ..nexus.nodes import group, dataset
        name = self.name if name is None else name
        depends_on = '.' if depends_on is None else depends_on
        return group(name, nx_class='NXpositioner', children=[
            self.to_log('value'),
            dataset('depends_on', depends_on),
        ])

