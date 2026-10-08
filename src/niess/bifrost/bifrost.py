
from ..instrument import Instrument, Mount, Motor, InstrumentParameter
from .primary import Primary
from .tank import Tank
from ..utilities import calibration
from ..components.component import Component
from scipp import vector
from scipp.spatial import rotations_from_rotvecs

#: Calibration keys that named the two angles before BIFROST adopted ECDC's names.
_RENAMED = {'a3_source': 'sample_rotation_source', 'a4_source': 'detector_tank_angle_source',
            'a3_pv_root': 'sample_rotation_pv_root',
            'a4_pv_root': 'detector_tank_angle_pv_root'}


@calibration
def instrument(params: dict):
    """BIFROST: the primary spectrometer, a sample turned by `sample_rotation` (a3), and
    the detector tank turned by `detector_tank_angle` (a4).

    The two angles take ECDC's names, which are what the real instrument's file uses.
    They are in degrees, which is what ESS publishes them in.
    """
    renamed = sorted(set(params) & set(_RENAMED))
    if renamed:
        raise TypeError('; '.join(f'{old!r} is now {_RENAMED[old]!r}' for old in renamed))
    sample = params.pop('sample', None)
    sample_rotation_source = params.pop('sample_rotation_source', 'sample_rotation')
    tank_angle_source = params.pop('detector_tank_angle_source', 'detector_tank_angle')
    # The real positioners, when there are any. Absent, both angles are simulation knobs
    # and a real conversion says so rather than inventing PVs for them.
    sample_rotation_pv_root = params.pop('sample_rotation_pv_root', None)
    tank_angle_pv_root = params.pop('detector_tank_angle_pv_root', None)
    origin = params.pop('origin', 'sample_origin')
    motor_topic = params.get('motor_topic', 'bifrost_motion')

    primary = Primary.from_calibration(**params)
    tank = Tank.from_calibration(**params)

    a3 = Motor(name='sample_rotation', unit='degrees', source=sample_rotation_source,
               topic=motor_topic, default=0.0, pv_root=sample_rotation_pv_root)
    a4 = Motor(name='detector_tank_angle', unit='degrees', source=tank_angle_source,
               topic=motor_topic, default=0.0, pv_root=tank_angle_pv_root)

    if sample is None:
        sample = Component(
            name='sample',
            position=vector((0, 0, 0), unit='m'),
            orientation=rotations_from_rotvecs(vector([0, 0, 0], unit='deg'))
        )

    return Instrument(
        name='bifrost', origin=origin, parts=(
            Mount(name='primary', content=primary),
            # the latest place a scan of a3 or a4 can split the simulation; see Mount
            Mount(name='sample', rotation=(0, a3, 0), relative_to=origin, content=sample,
                  split_before=True),
            Mount(name='tank', rotation=(0, a4, 0), relative_to=origin, content=tank),
        ), motors=(a3, a4), parameters=())


BIFROST = instrument()