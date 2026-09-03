"""Translator lookup for the NeXus target.

Created with ``hooks='nexus'``, so a class carrying ``__nexus_leaf__`` and friends is its
own translator and needs no registration -- which is how `RadialSlitBank` writes its own
NeXus without this package having to know it exists.

Its own module so that `niess.nexus.structure` and `niess.nexus.bifrost` can both fill it
without either importing the other.
"""
from __future__ import annotations

from ..dispatch import ClassHooks, NiessRegistry


class _EmittedHooks:
    """A class's own `__nexus_*__` hooks, with the leaf's body actually written out.

    Every NeXus translator says what a component *is* and lets the target place it:
    `@translator` takes the body its function returns and calls `emit`. A class hook has
    to mean the same thing by the same words, or a class describing its own conversion
    would have to know about `emit`, `_placed` and the pending list -- and would be the
    only translator that did.

    It did not, and nothing noticed, because the one hook anybody had written returned
    `None` on purpose: `RadialSlitBank` writes nothing. The first hook to return a real
    body found that the walk discards it, so the component simply went missing from the
    file -- no error, the same silent hole that provenance coverage exists to catch.
    """

    def __init__(self, hooks: ClassHooks):
        self._hooks = hooks

    def leaf(self, visit):
        from .structure import emit
        body = self._hooks.leaf(visit)
        # None is a translator declining to write anything, which is a thing a hook is
        # allowed to say -- see RadialSlitBank.
        if body is not None:
            emit(visit, body)
        return body

    def enter(self, visit):
        return self._hooks.enter(visit)

    def exit(self, visit, entered) -> None:
        self._hooks.exit(visit, entered)


class NiessNexusRegistry(NiessRegistry):
    """Translator lookup for the NeXus target.

    Created with ``hooks='nexus'``, so a class carrying ``__nexus_leaf__`` is its own
    translator. Registering wins, which is what an instrument-specific conversion needs
    -- BIFROST's detectors must not give another instrument's their pixel numbering
    merely because a module was imported.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent, hooks='nexus')

    def resolve_for_object(self, obj):
        """As the base class, but a class's own hooks get their body emitted."""
        builder = super().resolve_for_object(obj)
        return _EmittedHooks(builder) if isinstance(builder, ClassHooks) else builder

NEXUS_REGISTRY = NiessNexusRegistry()
