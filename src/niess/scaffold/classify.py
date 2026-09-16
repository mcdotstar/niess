"""Decide what each component of a `.instr` becomes, and assemble the result.

The output is a `Conversion`: a description of the whole instrument in niess terms, which
`niess.scaffold.emit` writes out as a module and `niess.scaffold.verify` checks. Nothing
here writes files.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from ..components import Opaque
from .fold import folder, symbol_table
from .place import Placement, placements
from .recipes import recipe_for


class Mapped(NamedTuple):
    """One component of the original, and what it became."""
    name: str
    mccode_type: str
    niess_class: type
    calibration: dict
    #: `placement.position` already has `position_offset` added, so this is where the
    #: niess object sits.
    placement: Placement
    #: Spindle-to-beam and the like: the vector between where the `.instr` placed the
    #: component and where the niess class measures from. `emit` has to write this out
    #: explicitly, because it rebuilds positions from the original `AT` chain and would
    #: otherwise reproduce the McStas convention rather than the niess one.
    position_offset: Any = None

    @property
    def is_opaque(self) -> bool:
        return self.niess_class is Opaque


class Conversion(NamedTuple):
    """A whole `.instr`, in niess terms."""
    name: str
    source: str
    components: tuple[Mapped, ...]
    #: Instrument parameters whose value was folded into a placement, so the geometry no
    #: longer responds to them. Emitted as named Python constants -- see `emit`.
    frozen: dict[str, float]
    #: Instrument parameters of the original carried forward, so component arguments
    #: that refer to them still resolve.
    parameters: tuple[Any, ...]
    #: Parameter name -> the component that now declares it itself. These are *not*
    #: carried forward: two declarations of one name collide, and the component's is the
    #: one that belongs to the model. The name and its default survive either way, so
    #: the generated instrument's signature is unchanged.
    subsumed: dict[str, str]
    origin: str | None

    @property
    def opaque(self) -> tuple[Mapped, ...]:
        return tuple(m for m in self.components if m.is_opaque)

    @property
    def modelled(self) -> tuple[Mapped, ...]:
        return tuple(m for m in self.components if not m.is_opaque)


def _opaque_parameters(instance, instrument_parameters: set[str]) -> dict:
    """A McStas component's arguments, as `Opaque` wants them.

    A constant becomes its value. Anything else is kept as **McCode source text**, which
    the assembler re-parses when the module is built -- so an argument written in terms of
    an instrument parameter keeps referring to it, and keeps working, because `Conversion`
    carries every original parameter forward.
    """
    parameters = {}
    for parameter in instance.parameters:
        value = parameter.value
        if value is None:
            continue
        if value.is_constant and value.has_value:
            parameters[parameter.name] = value.value
        else:
            parameters[parameter.name] = str(value)
    return parameters


def _extend_text(instance) -> str | None:
    if not instance.extend:
        return None
    return '\n'.join(str(block) for block in instance.extend)


def _as_opaque(instance, placement, instrument_parameters) -> Mapped:
    calibration = {
        'mccode_type': instance.type.name,
        'mccode_parameters': _opaque_parameters(instance, instrument_parameters),
        'when': None if instance.when is None else str(instance.when),
        'group': instance.group,
        'extend': _extend_text(instance),
        'split': None if instance.split is None else str(instance.split),
        'removable': instance.removable,
    }
    return Mapped(instance.name, instance.type.name, Opaque, calibration, placement)


def _geometry_symbols(instr) -> set[str]:
    """Instrument parameters a placement expression depends on.

    These are the ones whose geometric effect is frozen by the conversion, and the report
    names them for that reason.
    """
    names = {parameter.name for parameter in instr.parameters}
    used = set()
    for instance in instr.components:
        for expression in (*instance.at_relative[0], *instance.rotate_relative[0]):
            if expression.is_constant:
                continue
            used |= {name for name in names if expression.depends_on(name)}
    return used


def convert(instr, origin: str | None = None) -> Conversion:
    """Describe `instr` in niess terms, component by component.

    `origin` names the component everything else is measured against -- the sample
    position. niess records it on the `Instrument`; nothing here can guess it reliably,
    so it is the caller's to give and `None` is allowed.
    """
    fold = folder(instr)
    resolved = placements(instr, fold)
    instrument_parameters = {parameter.name for parameter in instr.parameters}

    components = []
    for instance in instr.components:
        placement = resolved[instance.name]
        recipe = recipe_for(instance.type.name)
        mapped = None

        if recipe is not None:
            try:
                result = recipe(instance, fold)
            except Exception:
                # A recipe that cannot cope is a component that becomes an `Opaque`, not
                # a conversion that fails. The report says which, and the instrument
                # still converts.
                result = None
            if result is not None:
                niess_class, calibration = result
                calibration = dict(calibration)
                offset = calibration.pop('position_offset', None)
                if offset is not None:
                    placement = placement._replace(
                        position=placement.position + offset.to(unit=placement.position.unit)
                    )
                mapped = Mapped(instance.name, instance.type.name, niess_class,
                                calibration, placement, offset)

        if mapped is None:
            mapped = _as_opaque(instance, placement, instrument_parameters)
        components.append(mapped)

    known = symbol_table(instr)
    frozen = {}
    for name in sorted(_geometry_symbols(instr)):
        try:
            frozen[name] = fold(known[name], name)
        except (ValueError, KeyError):
            continue

    components = tuple(components)
    subsumed = self_declared_parameters(instr.name, components)

    return Conversion(
        name=instr.name,
        source=instr.source or instr.name,
        components=components,
        frozen=frozen,
        parameters=tuple(p for p in instr.parameters if p.name not in subsumed),
        subsumed={name: owner for name, owner in subsumed.items()
                  if name in {p.name for p in instr.parameters}},
        origin=origin,
    )


def _parts(components):
    from ..instrument import Mount
    parts = []
    for mapped in components:
        entry = dict(mapped.calibration)
        entry.update({
            'name': mapped.name,
            'position': mapped.placement.position,
            'orientation': mapped.placement.orientation,
        })
        parts.append(Mount(name=mapped.name,
                           content=mapped.niess_class.from_calibration(entry)))
    return tuple(parts)


def self_declared_parameters(name: str, components) -> dict[str, str]:
    """Which run-time parameters the mapped components declare for themselves.

    A `DiscChopper` declares ``{name}speed`` and ``{name}delay``; a `Jaw` declares
    ``{name}_l`` and ``{name}_r`` -- and the original `.instr` almost certainly declared
    the same knobs, under the same names, since that is what the niess class was modelled
    on. Carrying both forward is not a duplicate to tidy up later: `ensure_runtime_parameter`
    refuses an inconsistent redeclaration, so the generated module would not build.

    Found by emitting once into a throwaway assembler with nothing carried forward and
    reading back what appeared. That costs one extra emission and needs no per-class
    knowledge, so a recipe added later is covered without touching this.
    """
    from ..instrument import Instrument
    from ..mccode import to_mccode

    trial = Instrument(name=name, origin=None, parts=_parts(components), parameters=())
    emitted = to_mccode(trial, insert_provenance_metadata=False)

    owners = {}
    for mapped in components:
        for parameter in emitted.parameters:
            if parameter.name.startswith(mapped.name):
                owners.setdefault(parameter.name, mapped.name)
    for parameter in emitted.parameters:
        owners.setdefault(parameter.name, '(a component)')
    return owners


def to_instrument(conversion: Conversion):
    """Build the `Instrument` a conversion describes, without generating any source.

    This is what `niess.scaffold.verify` measures, and what makes the conversion testable
    before a line of Python has been written out.
    """
    from ..instrument import Instrument

    return Instrument(
        name=conversion.name,
        origin=conversion.origin,
        parts=_parts(conversion.components),
        parameters=tuple(conversion.parameters),
    )
