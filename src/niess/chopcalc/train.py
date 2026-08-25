"""The chopper train, read off the tree.

`niess.chopcalc.via_instr` reads an emitted McStas instrument, and it does so
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


def _windows(disc) -> tuple[tuple[str, str], ...]:
    """Every opening, in chopper-lib's frame.

    chopper-lib measures from the disc's zero-angle point and puts the edge at angle
    ``a`` on the beam at ``delay + a / (360 * speed)``. A niess slit edge is measured
    from the top-dead-centre mark and ``{disc}delay`` is when ``beam_angle`` is on the
    beam -- so ``beam_angle`` is chopper-lib's zero point and an edge ``e`` sits at
    ``beam_angle - e``. The pair reverses because an opening counter-clockwise of the
    beam is reached by turning the other way.
    """
    beam = float(disc.beam_angle.to(unit='deg').value)
    return tuple((_c_double(beam - closing), _c_double(beam - opening))
                 for opening, closing in disc.slits())


def train_from_instrument(instrument, latest_emission: float | None = None,
                          skip=(), path_lengths=None) -> ChopperTrain:
    """Build the chopper train from a niess ``Instrument``.

    ``skip`` names discs to leave out; ``path_lengths`` overrides how far a neutron
    travels to reach one, for a disc whose route the flow graph cannot measure.
    """
    from ..components.chopper import DiscChopper, FermiChopper
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
        if isinstance(disc, FermiChopper) or not isinstance(disc, DiscChopper):
            continue
        if visit.name in skip:
            continue
        path = overrides.pop(visit.name, None)
        if path is None:
            path = beam_path_length(graph, places, source.id, visit.id)
        rows.append(ChopperEntry(
            name=visit.name,
            speed=disc.speed_parameter(),
            # every opening turns with the disc, so they share its delay; where each one
            # sits relative to that is what the windows say
            delay=disc.delay_parameter(),
            windows=_windows(disc),
            path=_c_double(path),
        ))

    if overrides:
        raise ChopcalcError(
            f'path_lengths names {sorted(overrides)}, which are not choppers in this '
            f'instrument'
        )

    return ChopperTrain(source=entry, choppers=tuple(rows), excluded=tuple(excluded))
