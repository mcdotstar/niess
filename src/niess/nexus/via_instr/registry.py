"""Translator registry for the NeXus target.

A translator takes a :class:`niess.nexus.instrument.Translation` and returns a
component body (see ``component_body``) -- or ``None`` to suppress the instance,
which the walk treats as a normal outcome distinct from "no translator found".
"""
from __future__ import annotations

from typing import Any, Callable

from ...dispatch import NiessRegistry

NexusTranslator = Callable[[Any], dict | None]


class NiessNexusRegistry(NiessRegistry[NexusTranslator]):
    """Three-tier translator lookup: niess source type, niess role, McCode type."""


DEFAULT_NEXUS_REGISTRY = NiessNexusRegistry()
