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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_STREAM_TOPIC = 'motors'
DEFAULT_CHOPPER_TOPIC = 'choppers'


class UndeclaredAxis(ValueError):
    """A real conversion reached an axis with no PV declared for it."""


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
                           source=motor.source or motor.name)


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
