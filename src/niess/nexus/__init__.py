"""McCode to ESS NeXus Structure JSON conversion.

Dispatches translators over the assembled ``mccode_antlr`` ``Instance`` tree, the
same handoff point :mod:`niess.brep` uses, and builds NeXus Structure JSON dicts
directly -- there is no intermediate NeXus object model.

    from niess.nexus import to_nexus_structure
    structure = to_nexus_structure(assembler.instrument, origin='sample_origin')

Instrument-specific translators are opt-in per conversion, through a registry that
extends the default one:

    from niess.nexus.bifrost import BIFROST_REGISTRY
    structure = to_nexus_structure(instr, origin='sample_origin',
                                   registry=BIFROST_REGISTRY)
"""
from .instrument import (
    DEFAULT_NXLOG_ROOT,
    NexusContext,
    Translation,
    component_body,
    to_nexus_structure,
)
from .loader import load_instr
# The node constructors a translator builds its output from, and the readers used to
# inspect a finished structure. Re-exported so writing a translator needs one import.
from .nodes import (
    attribute,
    children_of,
    dataset,
    find_child,
    get_attribute,
    group,
    node_name,
    stream,
)
from .off import NXoff
from .registry import DEFAULT_NEXUS_REGISTRY, NiessNexusRegistry
from .streams import resolve_stream

# Registers the default per-component-type translators on DEFAULT_NEXUS_REGISTRY.
# Instrument-specific translators are deliberately absent: they live in registries
# of their own (niess.nexus.bifrost.BIFROST_REGISTRY) and are selected per
# conversion by passing registry= to to_nexus_structure.
from . import translators as _translators  # noqa: F401

__all__ = [
    # conversion
    'to_nexus_structure',
    'load_instr',
    'NexusContext',
    'DEFAULT_NXLOG_ROOT',
    # writing translators
    'DEFAULT_NEXUS_REGISTRY',
    'NiessNexusRegistry',
    'Translation',
    'component_body',
    'resolve_stream',
    # building and reading nodes
    'attribute',
    'children_of',
    'dataset',
    'find_child',
    'get_attribute',
    'group',
    'node_name',
    'stream',
    'NXoff',
]
