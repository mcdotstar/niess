"""Read an assembled instrument: which source, which choppers, how far apart.

Everything here comes off the emitted components. Nothing is re-derived from a niess
calibration or from a parameter-naming convention, so an instrument niess did not build
works the same way -- which is the whole reason to keep it. What niess *did* build is
read from the tree instead, by `niess.chopcalc.train`, where a disc's speed and windows
are quantities on the disc rather than expressions to fold.

The arithmetic both routes share is in `niess.chopcalc.paths`.
"""
from __future__ import annotations

import logging
from math import degrees, fabs

from ..dispatch import component_type_name, expr_float
from ..provenance import NiessProvenance
from .model import ChopperEntry, Exclusion, SourceEntry
from .paths import (ChopcalcError, DEFAULT_LATEST_EMISSION, ESS_SOURCE_DURATION,
                    _c_double, beam_path_length)

logger = logging.getLogger(__name__)

CHOPPER_COMPONENT_TYPE = 'DiskChopper'

UNSUPPORTED_CHOPPER_TYPES = frozenset({
    'FermiChopper', 'FermiChopper_ILL', 'Vitess_ChopperFermi', 'Fermi_chop2a',
})

def _parameter(instance, name):
    """A parameter's value expression, or None when the component has no such parameter."""
    parameter = instance.get_parameter(name)
    return None if parameter is None else parameter.value

def _as_float(value, default=None):
    try:
        return expr_float(value)
    except (TypeError, ValueError):
        return default

def _identifier(value) -> str | None:
    """The name, when ``value`` is a bare symbol rather than a number or an expression."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text.isidentifier() else None

def find_source(instrument, graph, name: str | None = None):
    """The component neutrons come from.

    Not the one with the right parameters -- ``L_monitor``, ``TOFLambda_monitor``,
    ``DivLambda_monitor``, ``PolLambda_monitor`` and ``MeanPolLambda_monitor`` all take
    ``Lmin`` and ``Lmax``, so a wavelength monitor would answer to that. Not the one with
    the right category either: ``get_component_names_by_category('sources')`` is empty for
    an instrument built this way. The beam path is what distinguishes them -- neutrons
    enter at the source, so it is a root of the particle flow graph and a monitor is not.
    """
    if name is not None:
        try:
            instance = instrument.get_component(name)
        except RuntimeError:
            instance = None
        if instance is None:
            raise ChopcalcError(
                f'no component named {name!r}; source= must name one of the '
                f'instrument\'s components'
            )
        return instance

    roots = [n for n in graph.nodes if graph.in_degree(n) == 0]
    if len(roots) != 1:
        raise ChopcalcError(
            f'the beam path has {len(roots)} roots ({", ".join(sorted(roots)) or "none"}), '
            f'so the source is ambiguous; name it with source='
        )
    return instrument.get_component(roots[0])

def source_entry(instrument, instance, latest_emission: float | None) -> SourceEntry:
    """Verify the source can be narrowed, and read what the narrowing needs."""
    names = {}
    for which in ('Lmin', 'Lmax'):
        value = _parameter(instance, which)
        if value is None:
            raise ChopcalcError(
                f'source {instance.name!r} ({component_type_name(instance)}) has no '
                f'{which}, so there is no wavelength band to narrow'
            )
        identifier = _identifier(value)
        if identifier is None:
            raise ChopcalcError(
                f'source {instance.name!r} has {which}={value}, which is not an '
                f'instrument parameter. chopcalc narrows the band by writing through '
                f'&{which} at run time, and &{value} is not valid C. Give the source a '
                f'parameter instead -- in niess, '
                f'\'wavelength_minimum\': \'source_lambda_min/"angstrom" = 0.75\' in the '
                f'calibration.'
            )
        if instrument.get_parameter(identifier) is None:
            raise ChopcalcError(
                f'source {instance.name!r} has {which}={identifier}, which is not a '
                f'DEFINE INSTRUMENT parameter. Only those expand to an lvalue that '
                f'exists before init() runs, which is what chopcalc writes through.'
            )
        names[which] = identifier

    if latest_emission is not None:
        emission, note = _c_double(latest_emission), 'given to narrow_source_wavelengths'
    else:
        multiplier = _as_float(_parameter(instance, 'tmax_multiplier'))
        if multiplier is None:
            emission = _c_double(DEFAULT_LATEST_EMISSION)
            note = f'default, {DEFAULT_LATEST_EMISSION / ESS_SOURCE_DURATION:g} ESS pulses'
            logger.warning(
                'niess.chopcalc: source %r (%s) has no tmax_multiplier, so the latest '
                'emission time is unknown. Using %s s. Pass latest_emission= to set it; '
                'a longer time widens the band, which is the safe direction.',
                instance.name, component_type_name(instance), emission,
            )
        else:
            emission = f'{_c_double(multiplier)} * {ESS_SOURCE_DURATION:g}'
            note = 'tmax_multiplier * ESS_SOURCE_DURATION'

    return SourceEntry(
        name=instance.name,
        lambda_min=names['Lmin'],
        lambda_max=names['Lmax'],
        latest_emission=emission,
        latest_emission_note=note,
    )

def positions(instrument) -> dict[str, tuple[float, float, float]]:
    """Every component's absolute position, reduced to numbers."""
    resolved = {}
    for name, orient in instrument.resolve_orientations().items():
        place = orient.position()
        try:
            resolved[name] = tuple(
                expr_float(c) for c in (place.x, place.y, place.z)
            )
        except (TypeError, ValueError, AttributeError):
            continue  # depends on a run-time parameter; the caller excludes it
    return resolved

def _speed_expression(instance) -> str:
    """``nu``, or ``nu`` times ``nslit`` for equal, evenly spaced openings.

    chopper-lib's header documents that substitution: a disc with ``nslit`` identical
    openings presents them at ``nslit`` times its rotation frequency, and a delay means
    the same thing either way. The sign of ``nu`` is untouched, so direction survives.
    """
    nu = _parameter(instance, 'nu')
    nslit = _as_float(_parameter(instance, 'nslit'), 1.0)
    if nslit is None or nslit == 1.0:
        return str(nu)
    return f'({nu}) * {_c_double(nslit)}'

def _delay_expression(instance) -> str:
    """``delay``, unless a ``phase`` is set -- the branch DiskChopper itself takes."""
    delay = _parameter(instance, 'delay')
    phase = _parameter(instance, 'phase')
    literal_phase = _as_float(phase)
    if phase is None or literal_phase == 0.0:
        return str(delay)
    nu = _parameter(instance, 'nu')
    if literal_phase is not None:
        return f'({phase}) / (360.0 * fabs({nu}))'
    # a run-time phase: mirror DiskChopper's own `if (phase)` so the two never disagree
    return f'(({phase}) != 0 ? ({phase}) / (360.0 * fabs({nu})) : ({delay}))'

def _single_windows(instance) -> tuple[tuple[str, str], ...]:
    """The one opening of a plain ``DiskChopper``, centred on the path at its delay.

    chopper-lib's own ``single_to_multi_chopper`` builds exactly this pair, so describing
    a ``DiskChopper`` by its opening gives the row the same meaning it had when the
    calculation took a width instead.
    """
    theta = _parameter(instance, 'theta_0')
    literal = _as_float(theta)
    if literal is None:
        # a run-time width: halve it in C rather than refuse the chopper
        return ((f'-({theta}) / 2.0', f'({theta}) / 2.0'),)
    return ((_c_double(-literal / 2.0), _c_double(literal / 2.0)),)

def _disc_windows(group) -> tuple[tuple[str, str], ...]:
    """Every opening of a multi-opening disc, in chopper-lib's frame.

    chopper-lib measures a window from the disc's zero-angle point and puts the edge at
    angle ``a`` on the beam at ``delay + a / (360 * speed)``. niess measures a slit edge
    from the top-dead-centre mark, and ``{disc}delay`` is when the disc's
    ``beam_position`` is on the beam -- so ``beam_position`` *is* chopper-lib's zero-angle
    point, and an edge ``e`` sits at ``beam_position - e``.

    Subtracting is the whole of it. An opening counter-clockwise of the beam has to be
    brought round by turning clockwise, so it lies at a negative angle in this frame, and
    the pair reverses: the edge that opens last is the one nearest the zero point.
    """
    beam = float(group[0][1].extra.get('beam_position', 0.0))
    windows = []
    for _, provenance in group:
        opening, closing = provenance.extra['slit_edges']
        windows.append((_c_double(beam - closing), _c_double(beam - opening)))
    return tuple(windows)

def _check_group(group) -> None:
    """A group whose metadata disagrees with its components cannot be trusted.

    Stale metadata could make the band too narrow, which is the failure that loses
    neutrons, so this raises rather than guessing.
    """
    name = group[0][1].extra['disc_group_id']
    speeds = {str(_parameter(i, 'nu')) for i, _ in group}
    delays = {p.extra.get('delay_parameter') for _, p in group}
    if len(speeds) != 1:
        raise ChopcalcError(
            f'disc {name!r} has openings turning at different speeds ({sorted(speeds)}); '
            f'its provenance no longer matches the instrument'
        )
    if len(delays) != 1:
        raise ChopcalcError(
            f'disc {name!r} has openings with different delay parameters '
            f'({sorted(str(d) for d in delays)}); its provenance no longer matches the '
            f'instrument'
        )
    for instance, provenance in group:
        edges = provenance.extra['slit_edges']
        theta = _as_float(_parameter(instance, 'theta_0'))
        if theta is None or fabs(theta - (edges[1] - edges[0])) > 1e-9:
            raise ChopcalcError(
                f'opening {instance.name!r} of disc {name!r} is {theta} degrees wide but '
                f'its provenance says {edges[1] - edges[0]}; the instrument was edited '
                f'after niess emitted it'
            )

def build_train(instrument, *, source=None, skip=(), path_lengths=None,
                latest_emission=None, graph=None):
    """Everything the calculation needs, read off the assembled instrument.

    ``graph`` is the particle flow, used to find the source and to walk each chopper's
    path to it. McCode has no way to say that a beam branches, so an instrument whose
    flow is not the order its components are declared in -- BIFROST after the sample,
    where one beam becomes many -- has to be handed the real one.
    """
    from .model import ChopperTrain

    graph = instrument.build_flow_graph() if graph is None else graph
    places = positions(instrument)
    overrides = dict(path_lengths or {})
    skip = set(skip)

    source_instance = find_source(instrument, graph, source)
    entry = source_entry(instrument, source_instance, latest_emission)

    singles, groups, excluded = [], {}, []
    for instance in instrument.components:
        type_name = component_type_name(instance)
        if type_name in UNSUPPORTED_CHOPPER_TYPES:
            excluded.append(Exclusion(
                instance.name, (instance.name,),
                f'{type_name} cannot be described by a chopper_parameters row'))
            continue
        if type_name != CHOPPER_COMPONENT_TYPE:
            continue
        if instance.name in skip:
            excluded.append(Exclusion(instance.name, (instance.name,), 'skipped by the caller'))
            continue

        if _as_float(_parameter(instance, 'isfirst'), 0.0):
            raise ChopcalcError(
                f'chopper {instance.name!r} has isfirst=1, so it re-times neutrons '
                f'rather than absorbing them and every downstream delay is measured '
                f'from a different zero. The chopper-train model does not apply.'
            )

        # Grouped on the tag rather than on which Python class emitted it: every disc
        # records its openings, and only a disc split across several components carries
        # a group id saying which instances have to be put back together.
        provenance = NiessProvenance.from_instance(instance)
        if provenance is not None and provenance.extra.get('disc_group_id') is not None:
            groups.setdefault(provenance.extra['disc_group_id'], []).append(
                (instance, provenance))
            continue
        if instance.group:
            excluded.append(Exclusion(
                instance.name, (instance.name,),
                f'it is in McStas GROUP {instance.group!r}, whose members are '
                f'alternatives rather than a series, and it carries no slit_edges to '
                f'build an envelope from'))
            continue
        if any(_parameter(instance, p) is None for p in ('nu', 'theta_0', 'delay')):
            excluded.append(Exclusion(
                instance.name, (instance.name,), 'nu, theta_0 or delay is unset'))
            continue
        singles.append(instance)

    rows = []
    for instance in singles:
        path = overrides.pop(instance.name, None)
        if path is None:
            try:
                path = beam_path_length(graph, places, entry.name, instance.name)
            except ChopcalcError as error:
                excluded.append(Exclusion(instance.name, (instance.name,), str(error)))
                continue
        nslit = _as_float(_parameter(instance, 'nslit'), 1.0)
        rows.append(ChopperEntry(
            name=instance.name,
            speed=_speed_expression(instance),
            delay=_delay_expression(instance),
            windows=_single_windows(instance),
            path=_c_double(path),
            note=None if nslit in (None, 1.0) else
            f'{nslit:g} identical, evenly spaced openings, as one at {nslit:g}x the '
            f'rotation frequency',
        ))

    for name, group in groups.items():
        _check_group(group)
        group.sort(key=lambda pair: pair[1].extra.get('disc_group_index', 0))
        path = overrides.pop(name, None)
        if path is None:
            path = beam_path_length(graph, places, entry.name, group[0][0].name)
        rows.append(ChopperEntry(
            name=name,
            speed=str(_parameter(group[0][0], 'nu')),
            # every opening turns with the disc, so they share the disc's own delay;
            # where each one sits relative to it is what the windows say
            delay=str(group[0][1].extra['delay_parameter']),
            windows=_disc_windows(group),
            path=_c_double(path),
        ))

    if overrides:
        raise ChopcalcError(
            f'path_lengths names {sorted(overrides)}, which are not choppers in this '
            f'instrument'
        )

    # beam order, which is the order the neutron meets them
    order = {c.name: i for i, c in enumerate(instrument.components)}
    rows.sort(key=lambda row: order.get(row.name, len(order)))
    return ChopperTrain(source=entry, choppers=tuple(rows), excluded=tuple(excluded))
