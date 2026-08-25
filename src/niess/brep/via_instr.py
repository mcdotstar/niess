"""Solid geometry from an *emitted* instrument, rather than from the tree.

Kept for an instrument niess did not build, and for reading one back. What niess builds
is better drawn from the tree -- `niess.brep.assembly.to_assembly` -- which knows where
everything is without resolving expressions to find out, and which is not subject to a
released mccode-antlr silently exporting every solid at the origin.

The shape builders are shared with the tree route and live in `niess.brep.builders`;
only the walk differs. This module goes when the tree route is the only one.
"""
from __future__ import annotations

from .assembly import BREP_REGISTRY


class _SafeInstrumentDisplay:
    def __init__(self, instr):
        from mccode_antlr.display.component_display import ComponentDisplay

        self._instr = instr
        self._components = {}
        for instance in instr.components:
            try:
                component_display = ComponentDisplay(instance.type)
                if not component_display.is_empty():
                    self._components[instance.name] = component_display
            except Exception:
                continue

def instrument_to_assembly(instr, params: dict[str, float] | None = None, registry=None):
    """Build solid geometry from an *emitted* instrument.

    Kept for an instrument niess did not build, and for reading one back. What niess
    builds is better converted from the tree -- :func:`niess.brep.to_assembly`
    -- which knows where everything is without resolving expressions to find out, and
    which is not subject to a released mccode-antlr silently exporting every solid at
    the origin.

    The shape builders are shared: they were always written against the McCode
    parameters a component reports, so they take those from an emitted instance here
    and from the object itself there.
    """
    from mccode_antlr.display.instrument_display import InstrumentDisplay
    from mccode_antlr.display.render.brep import instrument_to_assembly as upstream
    from ..dispatch import component_type_name, merged_params
    from ..provenance import NiessProvenance
    from .assembly import Subject

    instr_display = instr if isinstance(instr, InstrumentDisplay) else _SafeInstrumentDisplay(instr)
    resolver = BREP_REGISTRY if registry is None else registry

    from mccode_antlr.display.render.brep import BRepRegistry
    shim = BRepRegistry()
    for comp_type in {component_type_name(i) for i in instr_display._instr.components}:
        @shim.register(comp_type)
        def wrapper(instance, component_params, _resolver=resolver):
            builder = _resolver.resolve_builder(instance)
            if builder is None:
                return None
            provenance = NiessProvenance.from_instance(instance)
            return builder(Subject(
                name=instance.name, obj=None,
                params=merged_params(instance, component_params),
                extra={} if provenance is None else provenance.extra))

    return upstream(instr_display, params=params, registry=shim)

def save_step(assembly_or_instr, path, params: dict[str, float] | None = None, registry=None):
    from mccode_antlr.display.render.brep import save_step as upstream

    assembly = assembly_or_instr
    if hasattr(assembly_or_instr, 'components') or hasattr(assembly_or_instr, '_instr'):
        assembly = instrument_to_assembly(assembly_or_instr, params=params, registry=registry)
    return upstream(assembly, path)
