"""BIFROST's streams as ECDC binds them for the real instrument.

`bindings.yaml` beside this file is a verbatim copy of ECDC's; see `UPSTREAM.md` for
where it came from and how to refresh it. niess names BIFROST's components as ECDC
names them, so a binding's key is also where niess writes the log. No mapping between
the two is kept.

    from niess.bifrost import BIFROST
    from niess.bifrost.ecdc import bifrost_streams
    from niess.nexus import to_nexus_structure
    from niess.nexus.bifrost import BIFROST_REGISTRY

    to_nexus_structure(BIFROST, registry=BIFROST_REGISTRY, streams=bifrost_streams())
"""
from __future__ import annotations

from functools import cache
from importlib.resources import files

#: Topics for anything the simulation publishes that ECDC does not bind: the mask's
#: edges, for instance. They are ECDC's topics for the same kind of thing.
MOTION_TOPIC = 'bifrost_motion'
CHOPPER_TOPIC = 'bifrost_choppers'

#: Bindings niess deliberately does not write, by key prefix, each with the reason.
#: Every binding must be used or listed here; `tests/test_bifrost_ecdc_bindings.py`
#: checks, so a refresh that adds one is noticed.
NOT_SIMULATED: dict[str, str] = {
    'source.': 'accelerator and target state, which a simulation does not have',
    'goniometer_lower.': 'not simulated',
    'goniometer_upper.': 'not simulated',
    'attenuator_': 'not simulated',
    'get_lost_tube.': 'not simulated',
    'sample_jaws.distance_from_guide_exit': 'niess places the sample jaws at a fixed '
                                            'distance',
    '.potentiometer_value': 'a second readback of the same edge; a simulation has one',
    '_monitor.data': 'the simulated monitors publish McStas histograms, whose streams '
                     'must describe what McStas produces rather than what the cbm EFU '
                     'would; with efu_monitors=True each publishes what its CbmChannel '
                     'configures the EFU to',
}


def bindings_path():
    """Where the vendored ECDC bindings file is."""
    return files(__name__) / 'bindings.yaml'


@cache
def bindings():
    """ECDC's bindings for BIFROST, keyed by NeXus path."""
    from types import MappingProxyType
    from ...nexus.bindings import load_bindings
    return MappingProxyType(load_bindings(bindings_path()))


#: Bindings niess writes although a prefix above would exclude them.
SIMULATED_ANYWAY = ('source.current',)


def not_simulated(key: str) -> str | None:
    """Why niess does not write the log bound to ``key``, or ``None`` if it does."""
    if key in SIMULATED_ANYWAY:
        return None
    for pattern, reason in NOT_SIMULATED.items():
        if pattern in key:
            return reason
    return None


def bifrost_streams(simulated: bool = True, **kwargs):
    """A binder writing BIFROST's streams as ECDC binds them.

    ``simulated=True`` is a simulation made to look like the real instrument. See
    `niess.nexus.bindings.BoundStreams` for what that includes and how the simulated
    sources are kept distinct from the real ones.
    """
    from ...nexus.bindings import BoundStreams
    options = dict(topic=MOTION_TOPIC, chopper_topic=CHOPPER_TOPIC) | kwargs
    return BoundStreams(bindings(), simulated=simulated, **options)
