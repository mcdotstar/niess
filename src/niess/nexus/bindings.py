"""Where a driven axis's numbers come from: a simulation knob, or a real motor.

One instrument tree, two files. A simulated run reads a McCode instrument parameter off
a `motors` topic; a real run reads an EPICS positioner, which ESS expects to appear as
three logs off one PV root -- `{root}.RBV` as `value`, `{root}.VAL` as `target_value`,
`{root}.DMOV` as `idle_flag`. Nothing about the instrument changes between the two: a
jaw still has a left edge and the tank still turns by a4. So the difference belongs
here, and the tree carries the PV roots without caring which file is being written.

    to_nexus_structure(bifrost)                  # simulated, the default
    to_nexus_structure(bifrost, streams=REAL)    # against the real positioners

There used to be two answers to "where does this axis's value come from": components
went through `NexusContext.streams`, while a motorised frame read `Motor.source`
straight off the object. A mode switch could only ever have covered one of them, so
both now come through `NexusContext.axis`.

A third binder, `BoundStreams`, reads the answers from a facility bindings file rather
than building them from a PV root -- see `load_bindings`.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_STREAM_TOPIC = 'motors'
DEFAULT_CHOPPER_TOPIC = 'choppers'

#: What a simulation puts in front of every source it serves over EPICS. It is also the
#: prefix the mccode-plumber mailbox uses for the PVs it serves.
SIMULATION_PREFIX = 'mcstas:'


class UndeclaredAxis(ValueError):
    """A real conversion reached an axis with no PV declared for it."""


class UnitMismatch(ValueError):
    """A knob declares a different unit from the one its binding publishes."""


@dataclass(frozen=True)
class Binding:
    """One entry of a facility bindings file: which stream fills one log.

    ``key`` is the log's NeXus path below `NXinstrument`, dot-separated:
    ``pulse_shaping_chopper_1.rotation_speed`` or ``sample_jaws.left.value``.
    ``source_type`` says who produces the stream. A ``forwarder`` source is an EPICS PV,
    and an ``efu`` source is a name chosen by an event formation unit.
    """
    key: str
    schema: str
    source: str
    topic: str
    source_type: str = 'forwarder'
    dtype: Optional[str] = None
    value_units: Optional[str] = None
    #: Schema-specific keys, e.g. a da00 binding's ``variables`` and ``constants``.
    extra: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def group(self) -> str:
        """The key of the group this log belongs to."""
        return self.key.rpartition('.')[0]

    @property
    def log(self) -> str:
        """The log's own name within its group."""
        return self.key.rpartition('.')[2]


_BINDING_FIELDS = ('schema', 'source', 'topic', 'source_type', 'dtype', 'value_units')


def parse_bindings(entries: Mapping[str, Mapping[str, Any]]) -> dict[str, Binding]:
    """Bindings from the mapping a bindings file holds, keyed as the file keys them."""
    bindings = {}
    for key, entry in entries.items():
        missing = [k for k in ('schema', 'source', 'topic') if k not in entry]
        if missing:
            raise ValueError(f'binding {key!r} has no {", ".join(missing)}')
        known = {k: entry[k] for k in _BINDING_FIELDS if k in entry}
        extra = {k: v for k, v in entry.items() if k not in _BINDING_FIELDS}
        bindings[key] = Binding(key=key, extra=extra, **known)
    return bindings


def load_bindings(path) -> dict[str, Binding]:
    """Read a facility bindings file, such as ECDC's ``bindings.yaml``.

    This is the file ECDC compiles, together with an ``instrument.yaml``, into the NeXus
    template the real instrument's filewriter uses. Each entry says which topic and
    source fill one log. Reading it here lets a niess file name the same streams
    without keeping a second copy of the answers.
    """
    from pathlib import Path
    import yaml
    with Path(path).open('r') as file:
        return parse_bindings(yaml.safe_load(file) or {})


@dataclass(frozen=True)
class LogBinding:
    """One log, resolved: the stream that fills it.

    ``parameter`` names the instrument parameter a simulation publishes the log from.
    It is written on the NXlog, so whatever serves the simulation's PVs can tell which
    parameter each source carries. ``None`` means nothing in the simulation feeds it:
    either the file is for a real run, or the value is computed elsewhere, as a
    chopper's top-dead-centre times are.
    """
    name: str
    module: str
    source: str
    topic: str
    units: str = ''
    dtype: str = 'double'
    parameter: Optional[str] = None


@dataclass(frozen=True)
class AxisBinding:
    """One driven axis, resolved: what to write in an f144 config for it.

    ``pv_root`` set means this axis is a real EPICS positioner and the three canonical
    logs follow from it. ``source`` set instead means a simulation parameter, and there
    is one log to write.
    """
    topic: str
    units: str = ''
    dtype: str = 'double'
    default: Any = None
    source: Optional[str] = None
    pv_root: Optional[str] = None
    #: The instrument parameter a simulation publishes ``source`` from.
    parameter: Optional[str] = None
    #: Every log, already resolved. When set, it takes precedence over ``source`` and
    #: ``pv_root``.
    logs: Optional[tuple[LogBinding, ...]] = None

    @property
    def canonical(self) -> bool:
        """Whether this axis can be written as an ESS-canonical NXpositioner."""
        return self.pv_root is not None

    def sources(self) -> dict[str, str]:
        """The f144 source for each canonical log name this axis has."""
        if not self.canonical:
            return {'value': self.source}
        return {'value': f'{self.pv_root}.RBV',
                'target_value': f'{self.pv_root}.VAL',
                'idle_flag': f'{self.pv_root}.DMOV'}


@dataclass(frozen=True)
class ChopperBinding:
    """One disc, resolved: what to write in its eight logs.

    A disc is not an axis. It has one controller rather than one driven degree of
    freedom, and every one of its logs hangs off that -- so it gets its own question
    rather than being squeezed through `bind`.
    """
    topic: str
    pv_root: Optional[str] = None
    tdc_channel: str = '00-TS-I'
    #: Every log, already resolved. When set, it takes precedence over ``pv_root``.
    logs: Optional[tuple[LogBinding, ...]] = None

    @property
    def canonical(self) -> bool:
        """Whether this disc can be written as an ESS-canonical NXdisk_chopper."""
        return self.pv_root is not None


def pv_root_for(owner, key: str, motor) -> str | None:
    """The EPICS positioner driving one axis, from the two places it may be declared.

    The `Motor` wins, because a Motor *is* an axis and knows its own PV. Then the
    component that owns the axis, which is how a jaw declares its two edges without
    having to invent a Motor for each of them.
    """
    root = getattr(motor, 'pv_root', None)
    if root:
        return root
    ask = getattr(owner, '__niess_pv_root__', None)
    return (None if ask is None else ask(key)) or None


def _dtype_of(motor) -> str:
    from .nodes import convert_type
    if motor.default is None:
        return 'double'
    return convert_type(motor.default)[0]


@dataclass(frozen=True)
class SimulatedStreams:
    """Sources are the simulation's own parameter names."""
    topic: str = DEFAULT_STREAM_TOPIC
    chopper_topic: str = DEFAULT_CHOPPER_TOPIC
    pulse_source: str = 'pulse'

    def chopper(self, disc) -> ChopperBinding:
        """A disc written from what the simulation knows, whatever it declares.

        A declared `pv_root` is ignored rather than honoured: a simulated file that
        named real PVs would be claiming values nothing published.
        """
        return ChopperBinding(topic=self.chopper_topic)

    def bind(self, owner, key: str, motor) -> AxisBinding:
        return AxisBinding(topic=motor.topic or self.topic, units=motor.unit,
                           dtype=_dtype_of(motor), default=motor.default,
                           source=motor.source or motor.name, parameter=motor.name)


@dataclass(frozen=True)
class RealStreams:
    """Sources are EPICS PV roots, declared on the components that own the axes.

    ``strict`` is the default because the failure it prevents is silent: a mistyped
    `pv_roots` key would otherwise produce a plausible-looking simulated axis inside a
    file that says it is real, and nothing downstream would ever say so. An instrument
    that really is only half wired up can pass ``strict=False`` and get the simulated
    source for the axes nobody has connected yet.
    """
    topic: str = DEFAULT_STREAM_TOPIC
    chopper_topic: str = DEFAULT_CHOPPER_TOPIC
    pulse_source: str = 'pulse'
    strict: bool = True

    def chopper(self, disc) -> ChopperBinding:
        """A disc written against its real controller, if it declares one."""
        root = getattr(disc, 'pv_root', None)
        if root is None:
            if self.strict:
                raise UndeclaredAxis(
                    f'no pv_root declared for chopper {getattr(disc, "name", disc)!r}. '
                    'Declare one on the disc, or pass streams=RealStreams(strict=False) '
                    'to simulate the choppers that are not wired up yet.')
            return SimulatedStreams(chopper_topic=self.chopper_topic).chopper(disc)
        return ChopperBinding(topic=self.chopper_topic, pv_root=root,
                              tdc_channel=getattr(disc, 'tdc_channel', '00-TS-I'))

    def bind(self, owner, key: str, motor) -> AxisBinding:
        root = pv_root_for(owner, key, motor)
        if root is None:
            if self.strict:
                raise UndeclaredAxis(
                    f'no pv_root declared for {motor.name!r}'
                    + (f' ({key!r} of {getattr(owner, "name", owner)!r})' if key else '')
                    + '. Declare one on the component, or pass '
                      'streams=RealStreams(strict=False) to simulate the axes that '
                      'are not wired up yet.')
            return SimulatedStreams(topic=self.topic).bind(owner, key, motor)
        return AxisBinding(topic=motor.topic or self.topic, units=motor.unit,
                           dtype=_dtype_of(motor), default=motor.default,
                           pv_root=root)


def _unit(knob) -> str:
    from ..components.motor import unquote
    return unquote(getattr(knob, 'unit', None))


@dataclass(frozen=True)
class BoundStreams:
    """Topics and sources read from a facility bindings file, one log at a time.

    `RealStreams` builds each log's source from a PV root and a fixed suffix. This binder
    looks the whole answer up instead, keyed by where the log sits in the file. That
    covers everything a template cannot, such as a per-disc TDC channel or a piezo
    motor's ``PzMtr`` record.

    Two kinds of file come from one bindings file:

    ``simulated=True`` (the default) is a simulation made to look like the real
    instrument. Only logs the simulation has a value for are written: a knob's
    ``value``, a disc's speed, delay and park angle, and the TDC times, which data
    reduction needs. A setpoint, a done flag, or a delay the electronics add has no
    counterpart in a simulation, so leaving it out keeps the file from claiming one.
    Every source the simulation serves over EPICS (``source_type: forwarder``) is
    prefixed with ``prefix``. The file then names the real instrument's topics, but a
    simulated PV can never be mistaken for the real one, even on the same network.
    Sources an event formation unit chooses (``source_type: efu``) are unchanged,
    because the EFU fixes them. Each simulated log carries a ``simulation_parameter``
    attribute naming the instrument parameter that feeds it.

    ``simulated=False`` writes every bound log, with the sources exactly as bound: a file
    for the real instrument.

    A knob must be declared in the unit its binding publishes. If it is not, the
    conversion raises `UnitMismatch`, so no conversion is ever hidden between the
    parameter and the stream. A knob with no binding gets a simulated source,
    ``prefix`` plus its own name, on ``topic`` (``chopper_topic`` for a disc), whatever
    topic the knob itself names: the binder, not the knob, decides where a facility's
    streams go. For a real file an unbound knob raises `UndeclaredAxis` unless
    ``strict=False``.

    ``pulse_source`` defaults to ``prefix`` + ``pulse``.
    """
    bindings: Mapping[str, Binding]
    simulated: bool = True
    prefix: str = SIMULATION_PREFIX
    topic: str = DEFAULT_STREAM_TOPIC
    chopper_topic: str = DEFAULT_CHOPPER_TOPIC
    pulse_source: Optional[str] = None
    strict: bool = True

    def __post_init__(self):
        if self.pulse_source is None:
            object.__setattr__(self, 'pulse_source', f'{self.prefix}pulse')

    def source(self, binding: Binding) -> str:
        """The source a log is written with, in this kind of file."""
        if self.simulated and binding.source_type == 'forwarder':
            return f'{self.prefix}{binding.source}'
        return binding.source

    def log(self, binding: Binding, knob=None, name: Optional[str] = None) -> LogBinding:
        """One bound log, checked against the knob that feeds it, if there is one."""
        units = binding.value_units or ''
        if knob is not None and binding.value_units is not None:
            declared = _unit(knob)
            if declared != binding.value_units:
                raise UnitMismatch(
                    f'{getattr(knob, "name", knob)!r} is declared in {declared!r} but '
                    f'{binding.key!r} publishes {binding.value_units!r}. Declare the '
                    'knob in the published unit and convert where the simulation '
                    'uses it.')
        return LogBinding(
            name=name or binding.log, module=binding.schema,
            source=self.source(binding), topic=binding.topic, units=units,
            dtype=binding.dtype or 'double',
            parameter=getattr(knob, 'name', None) if self.simulated else None)

    def _unbound(self, what: str, fix: str):
        if not self.simulated and self.strict:
            raise UndeclaredAxis(
                f'no binding for {what}. {fix}, or pass strict=False to simulate the '
                'parts that are not wired up yet.')

    def _simulated_log(self, name: str, knob, topic: str, dtype: str = 'double'
                       ) -> LogBinding:
        return LogBinding(name=name, module='f144',
                          source=f'{self.prefix}{knob.name}', topic=topic,
                          units=_unit(knob), dtype=dtype, parameter=knob.name)

    def chopper(self, disc) -> ChopperBinding:
        """A disc's logs, from the bindings for its group."""
        from .streams import CHOPPER_LOGS
        knobs = {'rotation_speed': disc.speed_parameter(),
                 'delay': disc.delay_parameter(),
                 'park_angle': disc.park_parameter()}
        bound = {log: self.bindings.get(f'{disc.name}.{log}')
                 for log, _, _ in CHOPPER_LOGS}
        if not any(bound.values()):
            self._unbound(f'chopper {disc.name!r}',
                          f'Add {disc.name}.<log> entries to the bindings')
            logs = [self._simulated_log(log, knobs[log], self.chopper_topic)
                    for log in knobs]
            logs.insert(1, LogBinding(name='top_dead_center', module='tdct',
                                      source=f'{self.prefix}{disc.name}_tdc',
                                      topic=self.chopper_topic, dtype=''))
            return ChopperBinding(topic=self.chopper_topic, logs=tuple(logs))
        logs = []
        for log, _, _ in CHOPPER_LOGS:
            binding, knob = bound[log], knobs.get(log)
            if binding is None:
                continue
            if self.simulated and knob is None and binding.schema != 'tdct':
                continue
            logs.append(self.log(binding, knob))
        return ChopperBinding(topic=self.chopper_topic, logs=tuple(logs))

    def _axis_group(self, owner, key: str, motor) -> Optional[str]:
        """Which bound group drives this axis: an owner's edge, or the knob itself."""
        owner_name = getattr(owner, 'name', None)
        candidates = ([f'{owner_name}.{key}'] if owner_name and key else []) + [motor.name]
        for candidate in candidates:
            if f'{candidate}.value' in self.bindings:
                return candidate
        return None

    def bind(self, owner, key: str, motor) -> AxisBinding:
        from .streams import POSITIONER_LOGS
        found = self._axis_group(owner, key, motor)
        common = dict(topic=self.topic, units=motor.unit,
                      dtype=_dtype_of(motor), default=motor.default)
        if found is None:
            self._unbound(f'{motor.name!r}'
                          + (f' ({key!r} of {getattr(owner, "name", owner)!r})'
                             if key else ''),
                          f'Add a {motor.name}.value entry to the bindings')
            log = self._simulated_log('value', motor, self.topic, dtype=_dtype_of(motor))
            return AxisBinding(**common, logs=(log,))
        logs = []
        for name in POSITIONER_LOGS:
            binding = self.bindings.get(f'{found}.{name}')
            if binding is None or (self.simulated and name != 'value'):
                continue
            logs.append(self.log(binding, motor if name == 'value' else None))
        return AxisBinding(**common, logs=tuple(logs))

    def pulse(self) -> Optional[LogBinding]:
        """The per-pulse reference sample, if ``source.current`` is bound.

        No simulation parameter feeds it. Whatever serves the simulation's pulse clock
        publishes it, one sample per pulse.
        """
        binding = self.bindings.get('source.current')
        return None if binding is None else self.log(binding)

    def stream(self, name: str, log: str = 'data') -> Optional[dict]:
        """A detector's or monitor's stream selection, or ``None`` if it is not bound."""
        binding = self.bindings.get(f'{name}.{log}')
        if binding is None:
            return None
        selection = {'module': binding.schema, 'topic': binding.topic,
                     'source': self.source(binding)}
        if binding.schema == 'da00':
            selection['config'] = {'topic': binding.topic,
                                   'source': self.source(binding), **binding.extra}
        return selection


SIMULATED = SimulatedStreams()
REAL = RealStreams()

_ALIASES = {'simulated': SIMULATED, 'sim': SIMULATED, 'real': REAL, 'epics': REAL}


def as_streams(spec) -> Any:
    """Accept a binder, or the name of one."""
    if spec is None:
        return SIMULATED
    if isinstance(spec, str):
        try:
            return _ALIASES[spec]
        except KeyError:
            raise ValueError(f'Unknown stream mode {spec!r}; '
                             f'expected one of {sorted(_ALIASES)}') from None
    return spec
