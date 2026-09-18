"""Turn mccode-antlr's orientation algebra into a NeXus transformation chain.

``Instr.resolve_orientations()`` does the geometry; this module only renders its
``Orient``/``Parts``/``Part`` output as ``NXtransformations`` children, each one
depending on the previous so the chain reproduces the McCode placement.

Ported from ``moreniius.mccode.orientation`` with ``NXfield`` replaced by the
dataset/group dicts of :mod:`niess.nexus.nodes`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from typing import TYPE_CHECKING

from .expression import parameter_node

if TYPE_CHECKING:
    from .instrument import NexusContext

logger = logging.getLogger(__name__)

# A transformation whose position and rotation are both identity: the chain still
# needs a link in it so dependents have something to point at.
EMPTY_TRANSFORMATION = None


@dataclass
class NXPart:
    """One ``Part`` of an orientation -- a single translation or rotation."""
    context: 'NexusContext'
    part: object

    def _transformation(self, name, value, *, vector, depends_on, transformation_type, units):
        resolved = self.context.resolve(value)
        return parameter_node(name, resolved, attrs={
            'vector': self.context.literal(vector),
            'depends_on': depends_on,
            'transformation_type': transformation_type,
            'units': units,
        })

    def make_translation(self, name, norm, vec, dep):
        return self._transformation(
            name, norm,
            vector=list(vec), depends_on=dep,
            transformation_type='translation', units='m',
        )

    def translations(self, dep: str, name: str) -> list[tuple[str, dict]]:
        from mccode_antlr.instr import RotationPart
        from mccode_antlr.common import Expr

        if isinstance(self.part, RotationPart):
            raise RuntimeError('Part is a rotation!')

        pos = self.part.position()
        if any(isinstance(c, Expr) for c in (pos.x, pos.y, pos.z)):
            # A runtime-dependent position cannot be reduced to one direction and
            # magnitude, so emit one axis-aligned translation per non-zero component.
            translations = []
            for axis, component, vector in (
                    ('x', pos.x, [1, 0, 0]),
                    ('y', pos.y, [0, 1, 0]),
                    ('z', pos.z, [0, 0, 1]),
            ):
                if not component.is_zero:
                    next_name = f'{name}_{axis}'
                    translations.append(
                        (next_name, self.make_translation(next_name, component, vector, dep))
                    )
                    dep = next_name
            return translations

        norm = pos.length()
        vec = pos if norm.is_zero else pos / norm
        return [(name, self.make_translation(name, norm, vec, dep))]

    def _axis_angle(self):
        from mccode_antlr.instr import TranslationPart
        if isinstance(self.part, TranslationPart):
            raise RuntimeError('Part is a translation')
        try:
            return self.part.rotation_axis_angle
        except RuntimeError as error:
            logger.error(f'Failed to get rotation axis and angle: {error} for {self.part!r}')
            raise NotImplementedError from error

    def rotation(self, name: str, dep: str) -> dict:
        axis, angle, angle_unit = self._axis_angle()
        return self._transformation(
            name, angle,
            vector=list(axis), depends_on=dep,
            transformation_type='rotation', units=angle_unit,
        )

    def rotation_inverse(self, name: str, dep: str) -> dict:
        axis, angle, angle_unit = self._axis_angle()
        return self._transformation(
            name, angle,
            vector=[-v for v in axis], depends_on=dep,
            transformation_type='rotation', units=angle_unit,
        )

    def transformations(self, name: str, dep: str | None = None) -> list[tuple[str, dict]]:
        if self.part.is_translation and self.part.is_rotation:
            ops = self.translations(dep, name)
            rotation_name = f'{name}_r'
            return [*ops, (rotation_name, self.rotation(rotation_name, ops[-1][0]))]
        if self.part.is_translation:
            return self.translations(dep, name)
        if self.part.is_rotation:
            return [(name, self.rotation(name, dep))]
        return []


@dataclass
class NXParts:
    """A position stack and a rotation stack, rendered as a dependency chain."""
    context: 'NexusContext'
    position: object
    rotation: object

    def _transformations(self, name: str, dep: str, typ: str, stack) -> list[tuple[str, dict]]:
        transformations = []
        for i, op in enumerate(stack):
            parts = NXPart(self.context, op).transformations(f'{name}_{typ}{i}', dep)
            transformations.extend(parts)
            if parts:
                dep = parts[-1][0]
        return transformations

    def position_transformations(self, name: str, dep: str | None = None) -> list[tuple[str, dict]]:
        return self._transformations(name, dep or '.', 't', self.position.stack())

    def rotation_transformations(self, name: str, dep: str | None = None) -> list[tuple[str, dict]]:
        return self._transformations(name, dep or '.', 'r', self.rotation.stack())

    def rotation_inverse_transformations(self, name: str, dep: str | None = None) -> list[tuple[str, dict]]:
        dep = dep or '.'
        transformations = []
        for i, op in enumerate(reversed(list(self.rotation.stack()))):
            entry_name = f'{name}_ri{i}'
            transformations.append(
                (entry_name, NXPart(self.context, op).rotation_inverse(entry_name, dep))
            )
            dep = entry_name
        return transformations

    def transformations(self, name: str, dep: str | None = None) -> list[tuple[str, dict]]:
        parts = self.position_transformations(name, dep=dep)
        if parts:
            dep = parts[-1][0]
        parts = parts + self.rotation_transformations(name, dep=dep)
        if dep is not None and not parts:
            # Told to place this relative to something, but both the position and
            # the rotation are identity: record the dependency and nothing else.
            return [(dep, EMPTY_TRANSFORMATION)]
        return parts


@dataclass
class NXOrient:
    """A resolved ``Orient``, split into separate position and rotation stacks."""
    context: 'NexusContext'
    orient: object
    rotation: object | None = None
    """Rotation stack to use in place of the resolved one.

    For a component emitted turned relative to the object it describes -- a disc chopper,
    whose McCode component has to be turned for its disc to land on the right side of the
    beam -- the resolved rotation is the emitted one, and what belongs in the file is the
    object's own."""
    position: object | None = None
    """Position stack to use in place of the resolved one.

    The same again for where a component sits: a disc chopper's McCode origin is on the
    beam, because that is where its component expects to be, while the disc itself is
    centred on its spindle. The file records the spindle."""

    def __post_init__(self):
        self.parts = NXParts(
            self.context,
            self.orient.position_parts() if self.position is None else self.position,
            self.orient.rotation_parts() if self.rotation is None else self.rotation,
        )

    def transformations(self, name: str) -> dict[str, dict]:
        return dict(self.parts.transformations(name))

    def position_transformations(self, name: str, dep: str | None = None):
        return self.parts.position_transformations(name, dep)

    def rotation_transformations(self, name: str, dep: str | None = None):
        return self.parts.rotation_transformations(name, dep)

    def rotation_inverse_transformations(self, name: str, dep: str | None = None):
        return self.parts.rotation_inverse_transformations(name, dep)
