from .secondary import DirectSecondary, IndirectSecondary
from .crystals import IdealCrystal, Crystal
from .detectors import Wire, DiscreteWire, DiscreteTube, He3Tube
from .aperture import Aperture, Jaw, Slit
from .chopper import (Chopper, DiscChopper, DISC_CHOPPERS, FermiChopper,
                      NXDiskChopper)
from .collimator import Collimator, SollerCollimator, RadialCollimator
from .component import Component
from .filter import (
    Attenuator, Filter, NCrystalFilter, OrderedFilter, RadialFilterCollimator,
    make_aluminum
)
from .guide import EllipticGuide, TaperedGuide, StraightGuide, Guide, StraightGuides, TaperedGuides
from .moderator import ESSModerator, Moderator, PolygonESSModerator
from .monitors import FissionChamber, He3Monitor, BeamCurrentMonitor, GEM2D
from .opaque import Opaque
from .section import Section

__all__ = [
    'DirectSecondary',
    'IndirectSecondary',
    'IdealCrystal',
    'Crystal',
    'Wire',
    'DiscreteWire',
    'DiscreteTube',
    'He3Tube',
    'Aperture',
    'Jaw',
    'Slit',
    'Chopper',
    'DiscChopper',
    'DISC_CHOPPERS',
    'FermiChopper',
    'NXDiskChopper',
    'Collimator',
    'SollerCollimator',
    'RadialCollimator',
    'Component',
    'Attenuator',
    'Filter',
    'NCrystalFilter',
    'OrderedFilter',
    'RadialFilterCollimator',
    'make_aluminum',
    'Guide',
    'EllipticGuide',
    'TaperedGuide',
    'StraightGuide',
    'StraightGuides',
    'TaperedGuides',
    'Moderator',
    'FissionChamber',
    'He3Monitor',
    'BeamCurrentMonitor',
    'GEM2D',
    'Opaque',
    'ESSModerator',
    'PolygonESSModerator',
    'Section',
]

#: Renamed in 0.9.0: the component is the moderator an instrument views, not the
#: facility's source (for ESS, the proton accelerator).
_RENAMED = {'Source': 'Moderator', 'ESSource': 'ESSModerator'}


def __getattr__(name):
    if name not in _RENAMED:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    from warnings import warn
    warn(f'niess.components.{name} is now niess.components.{_RENAMED[name]}',
         DeprecationWarning, stacklevel=2)
    return globals()[_RENAMED[name]]
