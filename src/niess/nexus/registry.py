"""Translator lookup for the NeXus target.

Created with ``hooks='nexus'``, so a class carrying ``__nexus_leaf__`` and friends is its
own translator and needs no registration -- which is how `RadialSlitBank` writes its own
NeXus without this package having to know it exists.

Its own module so that `niess.nexus.structure` and `niess.nexus.bifrost` can both fill it
without either importing the other.
"""
from __future__ import annotations

from ..dispatch import NiessRegistry


class NiessNexusRegistry(NiessRegistry):
    """Translator lookup for the NeXus target.

    Created with ``hooks='nexus'``, so a class carrying ``__nexus_leaf__`` is its own
    translator. Registering wins, which is what an instrument-specific conversion needs
    -- BIFROST's detectors must not give another instrument's their pixel numbering
    merely because a module was imported.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent, hooks='nexus')

NEXUS_REGISTRY = NiessNexusRegistry()
