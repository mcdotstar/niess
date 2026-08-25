"""Chopper specs for `tof`, read off the tree.

`niess.tof` builds these from what `niess.chopcalc` extracted, which is C *text* --
`chopcalc` emits text on purpose, so a band recomputes when a chopper speed changes at
run time. `tof` configures one specific machine and needs numbers, so it parses the text
back: `ParameterValues.evaluate_text`, and `_fold` underneath it, which exists to work
around an mccode-antlr trap where identifiers become `McCodeParameter` while `Expr.evaluate`
substitutes plain `sympy.Symbol` and the substitution silently does nothing.

Reading the tree there is no text to parse. A disc's speed and delay are quantities on
the disc, and a run-time override is a value for the knob it declared -- which the disc
also names.
"""
from __future__ import annotations

from .mapping import ChopperSpec, spec_from_windows


def chopper_specs(instrument, values: dict | None = None, origin: float = 0.0,
                  skip=(), path_lengths=None) -> tuple[ChopperSpec, ...]:
    """Every disc in ``instrument``, as ``tof`` wants it.

    ``values`` overrides a knob by name -- ``{'chopperspeed': 20}`` -- which is what
    running the same instrument at a different speed means. The disc names its knobs, so
    the override needs no convention repeated here.

    ``origin`` is where the ``tof.Source`` these are paired with sits, and it belongs to
    the model rather than to the instrument: an ESS source in ``tof`` carries its own
    0.05 m facility offset, while the niess moderator is at the instrument origin. Pass
    ``source.distance`` to have the two agree.
    """
    from ..chopcalc.tree import train_from_instrument
    from ..components.chopper import DiscChopper
    from ..walk import visits

    values = dict(values or {})
    train = train_from_instrument(instrument, skip=skip, path_lengths=path_lengths)
    paths = {entry.name: float(entry.path) for entry in train.choppers}

    specs = []
    for visit in visits(instrument):
        disc = visit.obj
        if not isinstance(disc, DiscChopper) or visit.name not in paths:
            continue
        speed = values.get(disc.speed_parameter(),
                           float(disc.speed.to(unit='Hz').value))
        delay = values.get(disc.delay_parameter(),
                           float(disc.delay.to(unit='s').value))
        beam = float(disc.beam_angle.to(unit='deg').value)
        windows = tuple((beam - closing, beam - opening)
                        for opening, closing in disc.slits())
        specs.append(spec_from_windows(
            name=visit.name, windows=windows, delay=float(delay), speed=float(speed),
            distance=origin + paths[visit.name]))
    return tuple(sorted(specs, key=lambda spec: spec.distance))


def _knob(disc, which: str):
    """A chopper's knob name and its calibrated value, for one of speed or delay."""
    if which == 'speed':
        return disc.speed_parameter(), float(disc.speed.to(unit='Hz').value), 'Hz'
    return disc.delay_parameter(), float(disc.delay.to(unit='s').value), 's'


def to_tof_model(instrument, *, values: dict | None = None, neutrons: int = 1_000_000,
                 pulses: int | None = None, seed: int | None = None, skip=(),
                 path_lengths=None):
    """A ready-to-run ``tof.Model`` for ``instrument``, and what went into it.

    The instrument-reading version of this asks `niess.chopcalc` for a chopper train,
    which is C text, and parses the numbers back out. Here every number is on an object:
    a disc's speed and delay, a monitor's position, the source's wavelength band.

    ``values`` overrides a knob by name, which is what running the same instrument at a
    different chopper speed means.
    """
    import scipp as sc

    from ..components.chopper import DiscChopper
    from ..components.monitors import FrameMonitor
    from ..components.source import Source
    from ..walk import visits
    from .components import _tof, _facility_for
    from .parameters import Use

    tof = _tof()
    values = dict(values or {})
    seen = list(visits(instrument))

    source_visit = next((v for v in seen if isinstance(v.obj, Source)), None)
    if source_visit is None:
        raise ValueError('the instrument has no source, so there is nothing to model')

    band = {}
    for field, keyword in (('wavelength_minimum', 'wmin'),
                           ('wavelength_maximum', 'wmax')):
        parameter = getattr(source_visit.obj, field, None)
        name = getattr(parameter, 'name', None)
        if name is None:
            continue
        held = values.get(name, _default_of(parameter))
        if held is not None:
            band[keyword] = sc.scalar(float(held), unit='angstrom')

    facility = _facility_for(instrument, tof)
    extra = {}
    if pulses is not None:
        extra['pulses'] = int(pulses)
    if seed is not None:
        extra['seed'] = int(seed)
    source = tof.Source(facility=facility, neutrons=int(neutrons), **band, **extra)
    origin = float(source.distance.to(unit='m').value)

    specs = chopper_specs(instrument, values=values, origin=origin, skip=skip,
                          path_lengths=path_lengths)
    by_name = {spec.name: spec for spec in specs}

    train = _paths(instrument, skip=skip, path_lengths=path_lengths)
    components, detectors = [], []
    for visit in seen:
        name = visit.name
        if isinstance(visit.obj, DiscChopper) and name in by_name:
            components.append(_as_tof_chopper(tof, by_name[name]))
        elif isinstance(visit.obj, (FrameMonitor,)) and name in train:
            components.append(tof.Detector(distance=sc.scalar(origin + train[name],
                                                              unit='m'), name=name))
            detectors.append(name)

    sample = getattr(instrument, 'origin', None)
    if sample is not None and sample in train and sample not in detectors:
        components.append(tof.Detector(distance=sc.scalar(origin + train[sample],
                                                          unit='m'), name=sample))
        detectors.append(sample)

    used = []
    for visit in seen:
        if not isinstance(visit.obj, DiscChopper) or visit.name not in by_name:
            continue
        for which in ('speed', 'delay'):
            knob, default, unit = _knob(visit.obj, which)
            used.append(Use(name=knob, value=float(values.get(knob, default)),
                            default=default, unit=unit,
                            overridden=knob in values,
                            used_by=(f'{visit.name}.{which}',)))

    def rebuild(overrides):
        return to_tof_model(instrument, values={**values, **overrides},
                            neutrons=neutrons, pulses=pulses, seed=seed, skip=skip,
                            path_lengths=path_lengths)

    from .components import TofSetup
    return TofSetup(model=tof.Model(source=source, components=components),
                    source=source, choppers=tuple(specs),
                    detectors=tuple(detectors), parameters=tuple(used),
                    _rebuild=rebuild)


def _default_of(parameter):
    try:
        return float(str(parameter.value))
    except (AttributeError, TypeError, ValueError):
        return None


def _as_tof_chopper(tof, spec):
    import scipp as sc
    return tof.Chopper(
        frequency=sc.scalar(spec.frequency, unit='Hz'),
        open=sc.array(values=list(spec.open), dims=['cutout'], unit='deg'),
        close=sc.array(values=list(spec.close), dims=['cutout'], unit='deg'),
        phase=sc.scalar(spec.phase, unit='deg'),
        distance=sc.scalar(spec.distance, unit='m'),
        name=spec.name,
        direction=tof.AntiClockwise if spec.anticlockwise else tof.Clockwise,
    )


def _paths(instrument, skip=(), path_lengths=None) -> dict:
    """How far along the beam every placed thing is, from the source."""
    from ..chopcalc.discovery import ChopcalcError, beam_path_length
    from ..chopcalc.tree import _global_position
    from ..components.source import Source
    from ..walk import visits

    seen = list(visits(instrument))
    source = next(v for v in seen if isinstance(v.obj, Source))
    graph = instrument.to_graph()
    places = {}
    for visit in seen:
        if not hasattr(visit.obj, 'position'):
            continue
        try:
            places[visit.id] = _global_position(visit)
        except ChopcalcError:
            continue

    found = {}
    for visit in seen:
        if visit.id not in places:
            continue
        try:
            found[visit.name] = beam_path_length(graph, places, source.id, visit.id)
        except ChopcalcError:
            continue
    return found
