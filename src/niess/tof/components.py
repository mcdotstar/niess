"""Walk an emitted instrument and build the pieces of a ``tof.Model``."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..chopcalc.discovery import ChopcalcError, beam_path_length, find_source, positions
from ..provenance import NiessProvenance
from .mapping import ChopperSpec, spec_from_windows
from .parameters import ParameterValues, Use
from .registry import DEFAULT_TOF_REGISTRY


def _tof():
    """The scipp ``tof`` package, imported when it is actually needed.

    Absolute, so this reaches the real ``tof`` and not ``niess.tof``.
    """
    try:
        import tof
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise ImportError(
            "niess.tof needs the 'tof' package: pip install 'niess[tof]'"
        ) from error
    return tof


@dataclass
class Conversion:
    """What a builder is handed: one instance, and everything already worked out."""

    instrument: Any
    instance: Any
    values: ParameterValues
    distance: float
    """Metres along the beam from the source, plus the source's own distance."""
    provenance: NiessProvenance | None = None
    spec: ChopperSpec | None = None
    """The chopper this instance belongs to, already evaluated, when it is a disc."""

    @property
    def name(self) -> str:
        return self.instance.name


# -- builders -----------------------------------------------------------------

@DEFAULT_TOF_REGISTRY.register('niess.components.chopper.DiscChopper')
@DEFAULT_TOF_REGISTRY.register_component_type('DiskChopper')
def disc_chopper_builder(conversion: Conversion):
    """One ``tof.Chopper`` per disc, however many components the disc was emitted as.

    A disc with several openings emits one ``DiskChopper`` apiece; ``chopcalc`` has already
    put them back together, so every instance but the one carrying the disc declines.
    """
    provenance = conversion.provenance
    if provenance is not None and provenance.role == 'disc-opening-member':
        return None
    if conversion.spec is None:
        return None
    return conversion.spec.to_tof()


@DEFAULT_TOF_REGISTRY.register_component_type(
    'Frame_monitor', 'TOF_monitor', 'PSD_monitor', 'L_monitor', 'Monitor_nD')
def monitor_builder(conversion: Conversion):
    """A monitor is somewhere a time distribution is worth recording, which is a detector.

    ``Frame_monitor`` covers every niess monitor; the rest are for instruments niess did
    not build.
    """
    tof = _tof()
    import scipp as sc

    return tof.Detector(distance=sc.scalar(conversion.distance, unit='m'),
                        name=conversion.name)


# -- the walk -----------------------------------------------------------------

@dataclass(frozen=True)
class TofSetup:
    """A ready-to-run ``tof.Model``, and what went into it.

    Displaying this in a notebook answers "what do I need to provide?" -- which, for an
    instrument niess built, is usually nothing: every chopper knob is declared with the
    calibration's own value as its default. The knobs are listed anyway, because knowing
    which ones exist is the point of asking.
    """

    model: Any
    source: Any
    choppers: tuple[ChopperSpec, ...]
    detectors: tuple[str, ...]
    parameters: tuple[Use, ...]
    excluded: tuple[Any, ...] = ()
    notes: tuple[str, ...] = ()
    _rebuild: Any = field(default=None, repr=False, compare=False)

    def with_values(self, **overrides) -> 'TofSetup':
        """The same instrument again, with these instrument parameters replaced."""
        if self._rebuild is None:
            raise RuntimeError('this setup was not built from an instrument')
        return self._rebuild(overrides)

    def __repr__(self) -> str:
        lines = [f'TofSetup: {len(self.choppers)} chopper(s), '
                 f'{len(self.detectors)} detector(s)']
        for spec in self.choppers:
            sense = 'anticlockwise' if spec.anticlockwise else 'clockwise'
            lines.append(f'  chopper  {spec.name:28s} {spec.frequency:8.3f} Hz {sense:14s}'
                         f' {len(spec.open)} opening(s) at {spec.distance:8.4f} m')
        for name in self.detectors:
            lines.append(f'  detector {name}')
        if self.parameters:
            lines.append('')
            lines.append('  parameters used (override with with_values(...)):')
            for use in self.parameters:
                unit = f' {use.unit}' if use.unit else ''
                where = 'given' if use.overridden else 'default'
                lines.append(f'    {use.name:28s} = {use.value!r}{unit}  ({where})'
                             f'  <- {", ".join(use.used_by)}')
            if not any(use.overridden for use in self.parameters):
                lines.append('  nothing has to be provided; every value came from the '
                             'instrument itself.')
        for exclusion in self.excluded:
            lines.append(f'  left out: {exclusion.name} -- {exclusion.reason}')
        for note in self.notes:
            lines.append(f'  note: {note}')
        return '\n'.join(lines)

    def _repr_markdown_(self) -> str:
        rows = ['| parameter | value | unit | from | read by |',
                '| --- | --- | --- | --- | --- |']
        for use in self.parameters:
            rows.append(f'| `{use.name}` | {use.value!r} | {use.unit or ""} | '
                        f'{"given" if use.overridden else "instrument default"} | '
                        f'{", ".join(f"`{u}`" for u in use.used_by)} |')
        head = (f'**{len(self.choppers)} chopper(s), {len(self.detectors)} detector(s)** '
                f'— ready to `run()`.\n\n')
        if not self.parameters:
            return head + 'No instrument parameters were needed.'
        tail = ('\n\nNothing has to be provided; every value came from the instrument '
                'itself. Override any of them with `with_values(...)`.'
                if not any(u.overridden for u in self.parameters) else '')
        return head + '\n'.join(rows) + tail


def _facility_for(instrument, tof) -> str:
    """The pulse profile that matches this instrument, or the generic ESS one."""
    candidate = f'ess-{instrument.name}'.lower()
    library = getattr(tof.facilities, 'source_library', {})
    return candidate if candidate in library else 'ess'


def _build_source(instrument, source_instance, values, tof, *, neutrons, pulses, seed):
    import scipp as sc

    facility = _facility_for(instrument, tof)
    wmin = values.number(source_instance, 'Lmin')
    wmax = values.number(source_instance, 'Lmax')
    kwargs = {}
    if wmin is not None:
        kwargs['wmin'] = sc.scalar(float(wmin), unit='angstrom')
    if wmax is not None:
        kwargs['wmax'] = sc.scalar(float(wmax), unit='angstrom')
    if pulses is not None:
        kwargs['pulses'] = int(pulses)
    if seed is not None:
        kwargs['seed'] = int(seed)
    return tof.Source(facility=facility, neutrons=int(neutrons), **kwargs), facility


def _furthest_measurable(graph, places, source_name, instrument, given: str | None):
    """Where to put the last detector: the end of the beam that can still be measured.

    Not the flow graph's sink, which is only the sample on an instrument that stops there.
    A secondary spectrometer keeps going, and its components are usually placed against a
    run-time angle -- a tank that rotates -- so their distance along the beam is not a
    number until the simulation runs. `tof` flies neutrons in a straight line to a fixed
    distance, so it has nothing to say about those.

    The furthest component whose path from the source *does* resolve is the end of the
    part `tof` can model, and on a direct-geometry instrument that is the sample.
    """
    if given is not None:
        return given
    furthest, best = None, None
    for instance in instrument.components:
        if instance.name == source_name:
            continue
        try:
            path = beam_path_length(graph, places, source_name, instance.name)
        except Exception:
            # any reason the path cannot be measured -- a run-time position, no route --
            # means this is not somewhere tof can put a detector
            continue
        if best is None or path > best:
            furthest, best = instance.name, path
    return furthest


def to_tof_model(obj, *, source=None, values=None, neutrons: int = 1_000_000,
                 pulses: int | None = None, seed: int | None = None,
                 sample: str | None = None, source_name: str | None = None,
                 skip=(), path_lengths=None, graph=None, registry=None) -> TofSetup:
    """Build a ready-to-run ``tof.Model`` from an assembled instrument.

    Parameters
    ----------
    obj:
        An ``Assembler`` or an ``Instr``. A **top-level** assembler: a child from
        ``assembler.included(...)`` merges into its parent only when the block exits, so
        its components -- and every later section's -- are not visible yet.
    source:
        A ``tof.Source`` to use instead of building one. Building one downloads the
        facility's pulse profile on first use, so pass your own to stay offline.
    values:
        Instrument parameter values to use instead of the instrument's own defaults.
        A scipp scalar is converted to whatever unit the instrument declares, so a speed
        worked out in kHz or a delay in ms can be handed over as it comes.
    neutrons:
        How many to sample from each pulse.
    pulses:
        How many source pulses to simulate. More than one is what shows a chopper turning
        at a fraction of the source frequency doing its job: a disc at half of 14 Hz opens
        for every other pulse and absorbs the rest, which a single pulse cannot show.
        Taken from the source when omitted.
    seed:
        Fixes the sampling, so two runs can be compared rather than merely resembling
        each other.
    sample:
        The component to put a detector on at the end of the beam. Found from the beam
        path when omitted.
    graph:
        The particle flow through the instrument, as a ``networkx`` DiGraph. Every
        distance here is walked along it, and McCode has no way to say that a beam
        branches -- so an instrument whose flow is not the order its components are
        declared in, BIFROST after the sample among them, has to be handed the real one.
        Built from the instrument when omitted.
    """
    from ..chopcalc.discovery import build_train

    tof = _tof()
    import scipp as sc

    instrument = obj.instrument if hasattr(obj, 'instrument') else obj
    if getattr(obj, 'parent', None) is not None:
        raise ValueError(
            'to_tof_model needs the top-level Assembler, after every section has been '
            'added. A section\'s child Assembler is merged into its parent only on '
            'leaving the included() block, so its components are not visible yet.'
        )

    parameters = ParameterValues(instrument, values)
    graph = instrument.build_flow_graph() if graph is None else graph
    places = positions(instrument)
    source_instance = find_source(instrument, graph, source_name)

    notes = []
    if source is None:
        source, facility = _build_source(instrument, source_instance, parameters, tof,
                                         neutrons=neutrons, pulses=pulses, seed=seed)
        notes.append(f'source pulse from the {facility!r} profile')
    else:
        notes.append('source supplied by the caller')
    origin = float(source.distance.to(unit='m').value)

    excluded = ()
    specs: dict[str, ChopperSpec] = {}
    try:
        train = build_train(instrument, source=source_name, skip=skip,
                            path_lengths=path_lengths, graph=graph)
    except ChopcalcError as error:
        notes.append(f'no chopper train: {error}')
    else:
        excluded = train.excluded
        for entry in train.choppers:
            speed = parameters.evaluate_text(entry.speed, used_by=f'{entry.name}.speed')
            delay = parameters.evaluate_text(entry.delay, used_by=f'{entry.name}.delay')
            windows = [(parameters.evaluate_text(low), parameters.evaluate_text(high))
                       for low, high in entry.windows]
            path = parameters.evaluate_text(entry.path)
            if None in (speed, delay, path) or any(v is None for w in windows for v in w):
                notes.append(f'{entry.name}: left out, its description did not reduce to '
                             f'numbers')
                continue
            specs[entry.name] = spec_from_windows(
                name=entry.name, windows=windows, delay=delay, speed=speed,
                distance=origin + path)

    registry = DEFAULT_TOF_REGISTRY if registry is None else registry
    components, detector_names = [], []
    for instance in instrument.components:
        if instance.name == source_instance.name:
            continue
        builder = registry.resolve_builder(instance)
        if builder is None:
            continue
        provenance = NiessProvenance.from_instance(instance)
        spec = specs.get(instance.name)
        if spec is None and provenance is not None:
            spec = specs.get(provenance.extra.get('disc_group_id'))
        try:
            distance = origin + beam_path_length(graph, places, source_instance.name,
                                                 instance.name)
        except ChopcalcError as error:
            notes.append(f'{instance.name}: left out, {error}')
            continue
        built = builder(Conversion(instrument=instrument, instance=instance,
                                   values=parameters, distance=distance,
                                   provenance=provenance, spec=spec))
        if built is None:
            continue
        components.append(built)
        if getattr(built, 'kind', None) == 'detector':
            detector_names.append(built.name)

    sample_at = _furthest_measurable(graph, places, source_instance.name,
                                     instrument, sample)
    if sample_at is not None and sample_at not in detector_names:
        try:
            distance = origin + beam_path_length(graph, places, source_instance.name,
                                                 sample_at)
        except ChopcalcError as error:
            notes.append(f'{sample_at}: no sample detector, {error}')
        else:
            components.append(tof.Detector(distance=sc.scalar(distance, unit='m'),
                                           name=sample_at))
            detector_names.append(sample_at)

    model = tof.Model(source=source, components=components)

    def rebuild(overrides):
        merged = {**(values or {}), **overrides}
        return to_tof_model(obj, source=None, values=merged, neutrons=neutrons,
                            pulses=pulses, seed=seed, sample=sample,
                            source_name=source_name, skip=skip,
                            path_lengths=path_lengths, graph=graph, registry=registry)

    return TofSetup(
        model=model, source=source,
        choppers=tuple(specs[name] for name in sorted(specs, key=lambda n: specs[n].distance)),
        detectors=tuple(detector_names),
        parameters=parameters.uses(),
        excluded=tuple(excluded),
        notes=tuple(notes),
        _rebuild=rebuild,
    )
