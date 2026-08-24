"""McStas, as one translation target among several.

Emission used to be the trunk: `to_mccode` walked the tree itself, and everything else
-- NeXus, tof, CAD -- read what it produced. Here it reads the same walk every other
target reads, and what makes that believable is that the instrument it emits is
unchanged, byte for byte, against the goldens in `tests/data/baseline`.

What the walk supplies, and this no longer works out for itself:

  names       `channel_3_radial_filter_collimator` is the filter's own name under what
              the channel contributes, not an f-string rebuilt at emission time.
  frames      what a component is placed against, threaded down from the mounting.
  order       declaration order, which is beam order.

What stays here is everything McStas-shaped: the coordinate-frame `Arm`s that exist so
other components can be placed relative to them, the `%include` sections, the `WHEN` and
`EXTEND` clauses that carry per-particle state, and the generated C.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..dispatch import NiessRegistry
from ..walk import Context, Visit, walk


@dataclass
class McCodeContext(Context):
    """The assembler being built into, and the section scopes open around it."""
    assembler: Any = None
    scopes: list = field(default_factory=list)
    #: Per-visit frame overrides, keyed by visit id. A composite that emits a coordinate
    #: frame of its own puts its children in it this way. Once frames are declared nodes
    #: in the tree rather than emission artefacts, this goes away.
    frames: dict = field(default_factory=dict)
    #: Per-visit WHEN clauses, same idea: which channel a neutron was tagged with is
    #: per-particle state, so it is McStas's business and not the tree's.
    whens: dict = field(default_factory=dict)

    def push(self, opened) -> Any:
        """Open a nested `%include` and emit into it until it is closed."""
        child = opened.__enter__()
        self.scopes.append((opened, self.assembler))
        self.assembler = child
        return opened

    def pop(self) -> None:
        opened, parent = self.scopes.pop()
        self.assembler = parent
        opened.__exit__(None, None, None)


class NiessMcCodeRegistry(NiessRegistry):
    """Translator lookup for the McStas target, keyed on the niess class."""


MCCODE_REGISTRY = NiessMcCodeRegistry()


def _section_scope_name(visit: Visit) -> str:
    """What a nested section's sub-instrument is called.

    `Guides` inside `teaching` becomes `teaching_guides`, which is the name the emitted
    `%include` carries.
    """
    import re
    spaced = re.sub('([A-Z]+)', r'_\1', type(visit.obj).__name__).lower()
    return f'{visit.context.assembler.name}{spaced}'


@MCCODE_REGISTRY.register('niess.components.section.Section')
class SectionTranslator:
    """A section is a scope, not a component.

    Without `_flat` it becomes an `%include`d sub-instrument, so the emitted McStas
    mirrors how the beamline is thought about rather than being one flat list.
    """

    @staticmethod
    def enter(visit: Visit):
        if getattr(visit.obj, '_flat', False):
            return None
        return visit.context.push(
            visit.context.assembler.included(_section_scope_name(visit))
        )

    @staticmethod
    def exit(visit: Visit, entered) -> None:
        if entered is not None:
            visit.context.pop()


@MCCODE_REGISTRY.register('niess.components.component.Component')
class ComponentTranslator:
    """One component, placed in the frame the walk handed it.

    The emission itself is still the component's own `__mccode__`/`to_mccode`, which is
    where the knowledge of McStas component types and their parameters belongs. What
    changed is that the name and the frame come from the walk: a component whose emitted
    name differs from the one it was calibrated with is emitted as a renamed copy, so
    the tree it came from is left as it was.
    """

    @staticmethod
    def leaf(visit: Visit):
        from msgspec.structs import replace
        context = visit.context
        obj = visit.obj
        if visit.name != obj.name:
            obj = replace(obj, name=visit.name)
        frame = context.frames.get(visit.id, visit.frame)
        instance = obj.to_mccode(context.assembler, at=frame, rotate=frame)
        when = context.whens.get(visit.id)
        if when is not None:
            instance.WHEN(when)
        return instance


def to_mccode(instrument, registry=None, assembler=None):
    """Emit ``instrument`` as a McStas instrument.

    Pass an ``assembler`` to build into an existing one; otherwise one is made from the
    instrument's own name and flavour.
    """
    from mccode_antlr.assembler import Assembler

    if assembler is None:
        assembler = Assembler(instrument.name, flavor=instrument.flavor)
    context = McCodeContext(instrument=instrument, assembler=assembler)
    walk(instrument, MCCODE_REGISTRY if registry is None else registry, context=context)
    if context.scopes:
        raise RuntimeError(
            f'{len(context.scopes)} section scope(s) left open; a translator opened one '
            f'without closing it'
        )
    return assembler.instrument


# -- the BIFROST tank ----------------------------------------------------------
#
# Everything below is McStas-shaped and stays here. The coordinate-frame `Arm`s exist so
# other components can be placed relative to them; `secondary_cassette` and its `WHEN`
# clauses are per-particle state in a Monte Carlo trace; the radial slits are how a
# neutron gets tagged with the channel it entered. None of it is a thing in the beam, and
# none of it means anything to NeXus, tof or CAD.


@MCCODE_REGISTRY.register('niess.bifrost.tank.Tank')
class TankTranslator:
    """The radial slits, then the elastic monitor, then the nine channels."""

    @staticmethod
    def enter(visit: Visit):
        from ..mccode import (add_niess_metadata, ensure_registry,
                              ensure_runtime_line, ensure_user_var)
        context, tank = visit.context, visit.obj
        assembler = context.assembler

        ensure_registry(assembler, 'mcdotstar/mcstas-slit-radial@main')
        ensure_user_var(assembler, 'int', 'secondary_cassette',
                        'Secondary spectrometer analyzer cassette index')
        ensure_runtime_line(assembler, 'slitAngle/"degree" = 0.0')
        ensure_runtime_line(assembler, f'slitDistance/"m" = {tank.slit_radius.value}')

        positions = tank.slit_angles
        declared = 'slits_positions'
        assembler.declare_array('double', declared, positions,
                                source=__file__, line=0)
        slits = assembler.component('slits', 'Slit_radial_multi',
                                    at=((0, 0, 0), visit.frame))
        add_niess_metadata(slits, tank, source_name='slits',
                           role='physical-component')
        slits.set_parameters(slit_width=tank.slit_width,
                             offset='slitAngle*DEG2RAD', number=len(positions),
                             radius='slitDistance', height=0.2,
                             positions=declared)
        # `slit` is >=0 iff scattered; the tag every channel is then gated on
        slits.EXTEND('secondary_cassette = (SCATTERED) ? 1 + slit : -1;')

        # The monitor's slit was added last, so it is the last index
        context.whens[f'{visit.id}/monitor'] = \
            f'secondary_cassette == {len(positions)}'
        return slits

    @staticmethod
    def exit(visit: Visit, entered) -> None:
        pass


@MCCODE_REGISTRY.register('niess.bifrost.channel.Channel')
class ChannelTranslator:
    """A cassette frame turned about the sample, and everything hung from it."""

    @staticmethod
    def enter(visit: Visit):
        from ..mccode import add_niess_metadata
        context, channel = visit.context, visit.obj
        assembler = context.assembler
        index = visit.index
        name = visit.own_label                      # channel_3
        when = f'{1 + index} == secondary_cassette'

        cassette = assembler.component(f'{name}_arm', 'Arm',
                                       at=((0, 0, 0), visit.frame),
                                       rotate=((0, channel.cassette_angle.value, 0),
                                               visit.frame))
        add_niess_metadata(cassette, channel, source_name=f'{name}_arm',
                           role='reference-frame',
                           extra={'frame': 'cassette', 'channel': name})
        cassette.WHEN(when)

        for declaration in ('int secondary_scattered;', 'int analyzer;', 'int flag;'):
            assembler.ensure_user_var(declaration)

        # everything in the channel sits in the cassette frame
        for child in visit.children():
            context.frames[child.id] = cassette
        context.frames[visit.id] = cassette
        context.whens[f'{visit.id}/radial_filter_collimator'] = when
        return cassette

    @staticmethod
    def exit(visit: Visit, entered) -> None:
        pass


@MCCODE_REGISTRY.register('niess.bifrost.arm.Arm')
class ArmTranslator:
    """An analyzer and the detector it reflects into, with the frames between them.

    Emitted as one unit rather than walked, because the frames interleave with the
    components: the detector's frame is placed relative to the monochromator, so it
    cannot exist until the analyzer has been emitted. That is a McStas authoring choice
    -- the same frame could be built from the analyzer point at twice the angle -- so it
    lives here rather than in the tree. When frames become declared nodes this becomes
    four ordinary children.
    """

    @staticmethod
    def enter(visit: Visit):
        from scipp import vector
        from ..mccode import add_niess_metadata
        from ..walk import SKIP
        context, arm = visit.context, visit.obj
        assembler = context.assembler
        reference = context.frames.get(visit.id, visit.frame)

        channel = visit.ancestor(_channel_class())
        when = f'{1 + channel.index} == secondary_cassette'
        arm_when = f'0 == secondary_scattered && {when}'
        extend = (f'secondary_scattered = (SCATTERED) ? 1 : 0;\n'
                  f'analyzer = (SCATTERED) ? {1 + visit.index} : 0;')
        detector_when = f'{when} && {1 + visit.index}==analyzer'
        detector_extend = 'flag = (SCATTERED) ? 1 : 0;'

        stem = visit.name                            # channel_3_1
        point, mono = f'{stem}_analyzer_point', f'{stem}_monochromator'
        orient, triplet = f'{stem}_detector_angle', f'{stem}_triplet'
        theta = arm.analyzer_theta.value

        frame = assembler.component(point, 'Arm',
                                    at=((0, 0, arm.sample_analyzer_distance.value),
                                        reference),
                                    rotate=((0, 0, 90), reference))
        add_niess_metadata(frame, arm, source_name=point, role='reference-frame',
                           extra={'frame': 'analyzer-point', 'arm': stem})
        frame.WHEN(arm_when)

        arm.analyzer.to_mccode(assembler, source=reference.name, relative=point,
                               sink=triplet, theta=theta, name=mono, when=arm_when,
                               extend=extend, origin=vector([0, 0, 0], unit='m'))

        turned = assembler.component(orient, 'Arm', at=((0, 0, 0), mono),
                                     rotate=((0, theta, 0), mono))
        add_niess_metadata(turned, arm, source_name=orient, role='reference-frame',
                           extra={'frame': 'detector-angle', 'arm': stem})
        turned.WHEN(detector_when)

        arm.detector.to_mccode(assembler, relative=orient,
                               distance=arm.analyzer_detector_distance.value,
                               name=triplet, when=detector_when,
                               extend=detector_extend)
        return SKIP


def _channel_class():
    from ..bifrost.channel import Channel
    return Channel
