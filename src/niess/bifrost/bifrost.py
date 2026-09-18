
from ..instrument import Instrument, Mount, Motor, InstrumentParameter
from .primary import Primary
from .tank import Tank
from ..utilities import calibration
from ..components.component import Component
from scipp import vector
from scipp.spatial import rotations_from_rotvecs

@calibration
def instrument(params: dict):
    sample = params.pop('sample', None)
    a3_source = params.pop('a3_source', 'a3')
    a4_source = params.pop('a4_source', 'a4')
    # The real positioners, when there are any. Absent, a3 and a4 are simulation knobs
    # and a real conversion says so rather than inventing PVs for them.
    a3_pv_root = params.pop('a3_pv_root', None)
    a4_pv_root = params.pop('a4_pv_root', None)
    origin = params.pop('origin', 'sample_origin')
    motor_topic = params.get('motor_topic', 'bifrost_motors')

    primary = Primary.from_calibration(**params)
    tank = Tank.from_calibration(**params)

    a3 = Motor(name='a3', unit='degree', source=a3_source, topic=motor_topic,
               default=0.0, pv_root=a3_pv_root)
    a4 = Motor(name='a4', unit='degree', source=a4_source, topic=motor_topic,
               default=0.0, pv_root=a4_pv_root)

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
        ), motors=(a3, a4), parameters=())


BIFROST = instrument()