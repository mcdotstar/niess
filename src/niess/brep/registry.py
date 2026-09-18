"""Where the CAD shape builders are registered.

One registry, reached either way. The builders live in :mod:`niess.brep.components` and
take a :class:`niess.targets.brep.Subject`; how that subject was arrived at -- walking
the tree, or reading an emitted instrument -- is not their business.

``NiessBRepRegistry`` and ``DEFAULT_BREP_REGISTRY`` are the names this was published
under and they still work; they now name the registry in :mod:`niess.targets.brep`
rather than a second one.
"""
from __future__ import annotations

from ..targets.brep import BREP_REGISTRY, NiessBRepRegistry

#: The registry every builder is on.
DEFAULT_BREP_REGISTRY = BREP_REGISTRY

__all__ = ['DEFAULT_BREP_REGISTRY', 'NiessBRepRegistry']
