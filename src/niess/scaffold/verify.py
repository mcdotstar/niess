"""Prove a conversion by comparing where the components are.

`docs/how-to/translate-an-instr.md` is emphatic that this, and not a text diff, is the
test:

    Do not diff the generated text against the original -- it will never match, and
    should not: different names, different ordering, added metadata. Compare where the
    components actually *are*.

This is not decoration on top of the converter. It is what makes `niess.scaffold.recipes`
safe to write. Mapping a McStas component onto a niess class means re-deriving a placement
from a different set of numbers -- most sharply for `DiscChopper`, whose `position` is the
spindle while the emitted `AT` is the beam crossing -- and the way that goes wrong is a
component quietly ending up somewhere else. This catches exactly that.

Why it does not use ``Instr.resolve_orientations``
--------------------------------------------------

The obvious implementation asks `mccode_antlr` for both instruments' absolute placements
and compares them. That is what `docs/examples/verify_translation.py` does, and for the
teaching instrument -- every rotation zero -- it is fine.

It is not fine in general. ``resolve_orientations`` builds symbolic expressions through
``unary_expr`` (`mccode_antlr/common/expression/utils.py:35`), which constant-folds a
literal angle with ``sin_degree`` but, for a *symbolic* one, emits a bare ``sympy.sin(TT)``
and drops the degrees-to-radians conversion with it. So a component placed through
``ROTATED (0, TT, 0)`` resolves to ``10*sin(TT)``, which is right only if ``TT`` is in
radians -- and McStas angles are degrees. On ESS_IN5_reprate that puts four components
metres away from where the instrument actually puts them.

So both sides are measured with `niess.scaffold.place.placements`, which folds every angle
to a number *before* building a quaternion and therefore never reaches that branch.
Measuring both sides with the same code would make a systematic error cancel, so
`check_against_mccode` cross-checks that code against ``resolve_orientations`` on the
instruments where ``resolve_orientations`` is trustworthy -- those whose rotation chains
are entirely numeric.
"""
from __future__ import annotations

from typing import NamedTuple

from .fold import folder
from .place import placements


class Difference(NamedTuple):
    name: str
    expected: tuple[float, float, float]
    actual: tuple[float, float, float]
    distance: float


class Comparison(NamedTuple):
    """What a conversion got right, and what it did not."""
    matched: tuple[str, ...]
    #: Components of the original that moved.
    moved: tuple[Difference, ...]
    #: Components of the original with no counterpart at all.
    missing: tuple[str, ...]
    #: Components the conversion added. Legitimate -- a `DiscChopper` emits one instance
    #: per opening, a `Frame` emits an `Arm` -- so these are reported, never failed on.
    added: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.moved and not self.missing

    def report(self) -> str:
        lines = [f'{len(self.matched)} of {len(self.matched) + len(self.moved) + len(self.missing)}'
                 f' components in the same place']
        for difference in self.moved:
            lines.append(f'  MOVED   {difference.name}: {difference.expected} -> '
                         f'{difference.actual} ({difference.distance:.6g} m)')
        for name in self.missing:
            lines.append(f'  MISSING {name}')
        if self.added:
            lines.append(f'  added by the conversion: {", ".join(self.added)}')
        return '\n'.join(lines)


def _positions(instr) -> dict[str, tuple[float, float, float]]:
    resolved = placements(instr, folder(instr))
    return {name: tuple(float(v) for v in place.position.to(unit='m').value)
            for name, place in resolved.items()}


def compare(original, converted, tolerance: float = 1e-9) -> Comparison:
    """Every component of `original` must appear in `converted` in the same place.

    Both are `mccode_antlr` ``Instr`` objects: the instrument that was read, and the one
    the generated niess module emits.
    """
    before, after = _positions(original), _positions(converted)

    matched, moved, missing = [], [], []
    for name, expected in before.items():
        if name not in after:
            missing.append(name)
            continue
        actual = after[name]
        distance = sum((a - b) ** 2 for a, b in zip(expected, actual)) ** 0.5
        if distance > tolerance:
            moved.append(Difference(name, expected, actual, distance))
        else:
            matched.append(name)

    return Comparison(
        matched=tuple(matched),
        moved=tuple(moved),
        missing=tuple(missing),
        added=tuple(name for name in after if name not in before),
    )


def has_symbolic_rotation(instr) -> bool:
    """Whether any ``ROTATED`` angle in `instr` is an expression rather than a number.

    Where this is false, ``Instr.resolve_orientations`` can be trusted and
    `check_against_mccode` is meaningful.
    """
    return any(not angle.is_constant
               for instance in instr.components
               for angle in instance.rotate_relative[0])


def check_against_mccode(instr, tolerance: float = 1e-9) -> Comparison:
    """Cross-check `placements` against ``mccode_antlr``'s own resolution.

    An independent implementation of the same arithmetic, so that `compare` -- which
    measures both of its sides with `placements` -- is not merely self-consistent.

    Only valid when `has_symbolic_rotation` is false; raises otherwise rather than
    reporting a difference that is the upstream bug described in this module's docstring
    rather than anything about the conversion.
    """
    if has_symbolic_rotation(instr):
        raise ValueError(
            f'{instr.name} places components through a symbolic ROTATED angle, so '
            'Instr.resolve_orientations() is not a valid reference for it -- see the '
            'note in niess.scaffold.verify.'
        )

    fold = folder(instr)
    resolved = instr.resolve_orientations()
    ours = _positions(instr)

    matched, moved = [], []
    for name, actual in ours.items():
        expected = tuple(fold(x, name) for x in resolved[name].position())
        distance = sum((a - b) ** 2 for a, b in zip(expected, actual)) ** 0.5
        if distance > tolerance:
            moved.append(Difference(name, expected, actual, distance))
        else:
            matched.append(name)

    return Comparison(matched=tuple(matched), moved=tuple(moved), missing=(), added=())
