"""ESS NeXus Structure JSON from an *emitted* instrument, rather than from the tree.

Everything it needs, it recovers: the placement from `Instr.resolve_orientations`, the
run-time values by constant-folding DECLARE blocks, a detector's arc and triplet by
matching a regex against a generated `WHEN` clause. It works, and it costs a thousand
lines of reading back what the tree said in the first place -- which is why `niess.nexus`
reads the tree, and this is kept for a file niess did not write.

    from niess.nexus.via_instr import to_nexus_structure
    structure = to_nexus_structure(assembler.instrument, origin='sample_origin')

Instrument-specific translators are opt-in per conversion, through a registry that extends
the default one:

    from niess.nexus.via_instr.bifrost import BIFROST_REGISTRY
    structure = to_nexus_structure(instr, origin='sample_origin',
                                   registry=BIFROST_REGISTRY)

The node constructors and the stream helpers are *not* re-exported here: they are format
rather than route, and stay in `niess.nexus.nodes`, `.streams` and `.off`, shared with the
tree. This whole subpackage goes when reading a foreign `.instr` stops being served.
"""
from .instrument import (
    DEFAULT_NXLOG_ROOT,
    NexusContext,
    Translation,
    component_body,
    to_nexus_structure,
)
from .registry import DEFAULT_NEXUS_REGISTRY, NiessNexusRegistry

# Registers the default per-component-type translators on DEFAULT_NEXUS_REGISTRY.
# Instrument-specific translators are deliberately absent: they live in registries of
# their own (niess.nexus.via_instr.bifrost.BIFROST_REGISTRY) and are selected per
# conversion by passing registry= to to_nexus_structure.
from . import translators as _translators  # noqa: F401

__all__ = [
    'DEFAULT_NEXUS_REGISTRY',
    'DEFAULT_NXLOG_ROOT',
    'NexusContext',
    'NiessNexusRegistry',
    'Translation',
    'component_body',
    'to_nexus_structure',
]
