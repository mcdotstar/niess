"""The chopper train, read off the tree.

The route this replaced read an emitted McStas instrument, and it did so
deliberately: an instrument niess did not build works the same way. It is also four
hundred lines of recovering what the tree already says -- which disc is which, where a
multi-opening one came apart and how to put it back, and which knob sets its speed.

Reading the tree, a disc is a disc. Its openings are its own, its knobs are named by the
methods that declared them, and the only thing still to be worked out is how far a
neutron travels to reach it -- which is geometry either way.

What is produced is the same `ChopperTrain` the other route produces, so `emit.py` is
untouched: every field is C text, because a chopper speed is a run-time knob and the band
has to recompute when it changes.
"""
from __future__ import annotations

from .paths import (ChopcalcError, DEFAULT_LATEST_EMISSION, ESS_SOURCE_DURATION,
                    _c_double, beam_path_length, global_position)
from .model import ChopperEntry, ChopperTrain, SourceEntry
from ..components.chopper import DiscChopper, FermiChopper, NXDiskChopper


def _source_entry(visit, latest_emission: float | None) -> SourceEntry:
    """The source, and the two knobs the narrowing writes through."""
    from mccode_antlr.common import InstrumentParameter

    obj = visit.obj
    names = {}
    for which, field in (('Lmin', 'wavelength_minimum'), ('Lmax', 'wavelength_maximum')):
        value = getattr(obj, field, None)
        if not isinstance(value, InstrumentParameter):
            raise ChopcalcError(
                f'source {visit.name!r} has {field}={value!r}, which is not an '
                f'instrument parameter. chopcalc narrows the band by writing through '
                f'&{which} at run time, so it has to be one -- in a calibration, '
                f'\'{field}\': \'source_lambda_min/"angstrom" = 0.75\'.'
            )
        names[which] = value.name

    if latest_emission is not None:
        emission = _c_double(latest_emission)
        note = 'given to narrow_source_wavelengths'
    else:
        multiplier = getattr(obj, 'latest_emission_time', None)
        if multiplier is None:
            emission = _c_double(DEFAULT_LATEST_EMISSION)
            note = f'default, {DEFAULT_LATEST_EMISSION / ESS_SOURCE_DURATION:g} ESS pulses'
        else:
            factor = float(multiplier.to(unit='s').value) / ESS_SOURCE_DURATION
            emission = f'{_c_double(factor)} * {ESS_SOURCE_DURATION:g}'
            note = 'tmax_multiplier * ESS_SOURCE_DURATION'

    return SourceEntry(name=visit.name, lambda_min=names['Lmin'],
                       lambda_max=names['Lmax'], latest_emission=emission,
                       latest_emission_note=note)


def _speed(obj) -> str:
    if isinstance(obj, DiscChopper):
        return obj.speed_parameter()
    if isinstance(obj, NXDiskChopper):
        return obj.speed_parameter().name
    raise ValueError(f'speed unknown for {obj}')


def _delay(obj) -> str:
    if isinstance(obj, DiscChopper):
        return obj.delay_parameter()
    if isinstance(obj, NXDiskChopper):
        return obj.delay_parameter().name
    raise ValueError(f'delay unknown for {obj}')


def _beam(obj) -> str:
    return _c_double(obj.beam_angle.to(unit='deg').value)


def _aperture(obj) -> str:
    from scipp import atan2, sqrt, scalar
    radius = obj.radius.to(unit='m')
    half_width = (obj.width / 2).to(unit=radius.unit) if obj.width is not None else scalar(0., unit='m')
    height = obj.height.to(unit=radius.unit) if obj.height is not None else radius
    aperture = 2 * atan2(y=half_width, x=sqrt(radius**2 - half_width**2)-height)
    return _c_double(aperture.to(unit='deg').value)


def _edge_count(disc) -> int:
    if isinstance(disc, DiscChopper):
        return len(disc.nexus_slit_edges())
    if isinstance(disc, NXDiskChopper):
        return len(disc.edge_array_values())
    raise ValueError(f'count unknown for {disc}')


def _edges(disc) -> tuple[str, ...] | str:
    """Every opening, in chopper-lib's frame.

    There is nothing to convert. chopper-lib 4.0.0 measures from the same top-dead-centre
    mark the disc's ``slits()`` do, and takes ``beam_angle`` as a field of its own rather
    than expecting the caller to fold it in -- so the openings go across as written, in
    the order the component and the NeXus standard write them.
    """
    if isinstance(disc, DiscChopper):
        return tuple(_c_double(edge) for edge in disc.nexus_slit_edges())
    if isinstance(disc, NXDiskChopper):
        return disc.edge_array_identifier()
    raise ValueError(f"windows parameters unknown for {disc}")

def train_from_instrument(instrument, latest_emission: float | None = None,
                          skip=(), path_lengths=None) -> ChopperTrain:
    """Build the chopper train from a niess ``Instrument``.

    ``skip`` names discs to leave out; ``path_lengths`` overrides how far a neutron
    travels to reach one, for a disc whose route the flow graph cannot measure.
    """

    from ..components.source import Source
    from ..walk import visits

    seen = list(visits(instrument))
    sources = [v for v in seen if isinstance(v.obj, Source)]
    if not sources:
        raise ChopcalcError('the instrument has no source, so there is no band to narrow')
    source = sources[0]

    entry = _source_entry(source, latest_emission)
    graph = instrument.to_graph()
    places = {}
    for visit in seen:
        if hasattr(visit.obj, 'position'):
            try:
                places[visit.id] = global_position(visit)
            except ChopcalcError:
                continue

    overrides = dict(path_lengths or {})
    excluded, rows = [], []
    for visit in seen:
        disc = visit.obj
        if isinstance(disc, FermiChopper) or not isinstance(disc, (DiscChopper, NXDiskChopper)):
            continue
        if visit.name in skip:
            continue
        path = overrides.pop(visit.name, None)
        if path is None:
            path = beam_path_length(graph, places, source.id, visit.id)
        rows.append(ChopperEntry(
            name=visit.name,
            speed=_speed(disc),
            delay=_delay(disc),
            beam=_beam(disc),
            edge_count=_edge_count(disc),
            edges=_edges(disc),
            path=_c_double(path),
            aperture=_aperture(disc),
        ))

    if overrides:
        raise ChopcalcError(
            f'path_lengths names {sorted(overrides)}, which are not choppers in this '
            f'instrument'
        )

    return ChopperTrain(source=entry, choppers=tuple(rows), excluded=tuple(excluded))
