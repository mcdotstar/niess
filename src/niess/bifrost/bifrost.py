
from ..instrument import Instrument, Mount, InstrumentParameter
from .primary import Primary
from .tank import Tank
from ..utilities import calibration
from ..components.component import Component
from scipp import vector
from scipp.spatial import rotations_from_rotvecs

@calibration
def instrument(params: dict):
    sample = params.pop('sample', None)
    primary = Primary.from_calibration(**params)
    tank = Tank.from_calibration(**params)
    origin='sample_origin'
    a3 = InstrumentParameter.parse('a3/"deg" = 0')
    a4 = InstrumentParameter.parse('a4/"deg" = 0')

    if sample is None:
        sample = Component(
            name='sample',
            position=vector((0, 0, 0), unit='m'),
            orientation=rotations_from_rotvecs(vector([0, 0, 0], unit='deg'))
        )

    return Instrument(
        name='bifrost', origin=origin, parts=(
            Mount(name='primary', content=primary),
            Mount(name='sample', rotation=(0, a3, 0), relative_to=origin, content=sample),
            Mount(name='tank', rotation=(0, a4, 0), relative_to=origin, content=tank),
        ), parameters=(a3, a4))


BIFROST = instrument()