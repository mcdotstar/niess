"""ESS NeXus Structure JSON from a niess instrument.

    from niess.instrument import Instrument, Mount
    from niess.nexus import to_nexus_structure

    structure = to_nexus_structure(instrument)

Reads the tree: a component's position and orientation are on the component, a declared
`Frame` is a node, and a `depends_on` chain is the chain of frames a thing hangs from.

Writing a translator needs the node constructors, which are re-exported here so that takes
one import. They are shared with the other route, being format rather than route.

One thing this module deliberately does not import: `niess.nexus.bifrost`.
Instrument-specific translators live in registries of their own, and generic NeXus has no
business loading `niess.bifrost` to publish them.

Converting an instrument niess did *not* build, by reading emitted McStas back, was a
second route of some 1500 lines. It is gone: niess converts niess instruments.
"""
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
from .registry import NEXUS_REGISTRY, NiessNexusRegistry
from .streams import resolve_stream
from .structure import (
    DEFAULT_NXLOG_ROOT,
    NexusContext,
    component_body,
    emit,
    to_nexus_structure,
    translator,
)

__all__ = [
    # conversion
    'to_nexus_structure',
    'NexusContext',
    'DEFAULT_NXLOG_ROOT',
    # writing translators
    'NEXUS_REGISTRY',
    'NiessNexusRegistry',
    'component_body',
    'emit',
    'translator',
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
