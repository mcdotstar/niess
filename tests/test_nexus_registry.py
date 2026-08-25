"""Instrument-specific translators are scoped to the conversion that asks for them.

They used to be registered on the shared ``DEFAULT_NEXUS_REGISTRY`` at import time,
which made the opt-in per *process* rather than per conversion: once anything imported
``niess.nexus.bifrost``, every later conversion in that process picked up BIFROST's
translators. That is not hypothetical -- ``Detector_tubes`` is not a BIFROST-only
component, so another instrument using it would silently inherit BIFROST's ICD pixel
numbering and detector topic. Now each instrument has its own registry, extending the
default one.
"""
import pytest

from niess.nexus.registry import DEFAULT_NEXUS_REGISTRY, NiessNexusRegistry


class FakeInstance:
    """The minimum a registry looks at: a component type and no provenance."""

    def __init__(self, type_name):
        self.type = type('T', (), {'name': type_name, 'category': None})()

    @staticmethod
    def collect_metadata():
        return []


def test_importing_bifrost_leaves_the_default_registry_alone():
    before = DEFAULT_NEXUS_REGISTRY.registered_component_types()
    from niess.nexus import bifrost  # noqa: F401
    assert DEFAULT_NEXUS_REGISTRY.registered_component_types() == before

    for type_name in ('Monochromator_Rowland', 'Detector_tubes', 'Detector_time_tubes'):
        assert DEFAULT_NEXUS_REGISTRY.resolve_builder(FakeInstance(type_name)) is None


def test_frame_monitor_is_generic_not_bifrost_specific():
    """niess.components.monitors emits Frame_monitor for every instrument.

    Registered on BIFROST_REGISTRY it stranded every other instrument's monitors as
    NXcoordinate_system, silently discarding the da00 stream their METADATA carries,
    so it belongs on the default registry with the other monitor types.
    """
    from niess.nexus.translators import monitor_translator

    assert DEFAULT_NEXUS_REGISTRY.resolve_builder(
        FakeInstance('Frame_monitor')) is monitor_translator


def test_bifrost_registry_resolves_its_own_translators():
    from niess.nexus.bifrost import (
        BIFROST_REGISTRY, detector_tubes_translator, monochromator_rowland_translator,
    )

    assert BIFROST_REGISTRY.resolve_builder(
        FakeInstance('Monochromator_Rowland')) is monochromator_rowland_translator
    for type_name in ('Detector_tubes', 'Detector_time_tubes'):
        assert BIFROST_REGISTRY.resolve_builder(
            FakeInstance(type_name)) is detector_tubes_translator


def test_bifrost_registry_inherits_the_generic_translators():
    """Extending the default must not mean losing it."""
    from niess.nexus.bifrost import BIFROST_REGISTRY
    from niess.nexus.translators import diskchopper_translator

    assert BIFROST_REGISTRY.resolve_builder(
        FakeInstance('DiskChopper')) is diskchopper_translator
    assert DEFAULT_NEXUS_REGISTRY.registered_component_types() <= \
        BIFROST_REGISTRY.registered_component_types()


def test_unknown_types_still_resolve_to_nothing():
    from niess.nexus.bifrost import BIFROST_REGISTRY
    assert BIFROST_REGISTRY.resolve_builder(FakeInstance('Some_Other_Component')) is None


def test_a_child_registry_overrides_its_parent():
    """The more specific registry wins; the parent is a fallback, not an override."""
    parent = NiessNexusRegistry()
    child = NiessNexusRegistry(parent=parent)

    @parent.register_component_type('DiskChopper')
    def generic(t):
        return 'generic'

    @child.register_component_type('DiskChopper')
    def specific(t):
        return 'specific'

    assert parent.resolve_builder(FakeInstance('DiskChopper')) is generic
    assert child.resolve_builder(FakeInstance('DiskChopper')) is specific


def test_registering_on_a_child_does_not_touch_the_parent():
    parent = NiessNexusRegistry()
    child = NiessNexusRegistry(parent=parent)

    @child.register_component_type('OnlyOnTheChild')
    def only_child(t):
        return None

    assert child.resolve_builder(FakeInstance('OnlyOnTheChild')) is only_child
    assert parent.resolve_builder(FakeInstance('OnlyOnTheChild')) is None


@pytest.mark.parametrize('registry_name', ['default', 'bifrost'])
def test_detector_tubes_translation_follows_the_registry(registry_name):
    """End to end: the same instrument converts differently per registry choice."""
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.assembler import ensure_registry
    from niess.nexus import to_nexus_structure
    from niess.nexus.bifrost import BIFROST_REGISTRY
    from niess.nexus.nodes import find_child, get_attribute

    assembler = Assembler('not_bifrost', flavor=Flavor.MCSTAS)
    ensure_registry(assembler, 'mcdotstar/mcstas-detector-tubes@main')
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    assembler.component('sample', 'Arm', at=((0, 0, 1), 'origin'))
    assembler.component('tubes', 'Detector_tubes', at=((0, 0, 2), 'origin'),
                        parameters=dict(N=3, no=100, width=0.1, height=0.2, radius=0.005))

    registry = BIFROST_REGISTRY if registry_name == 'bifrost' else None
    structure = to_nexus_structure(assembler.instrument, origin='sample', registry=registry)
    tubes = find_child(structure['children'][0]['children'][0], 'tubes')

    if registry_name == 'bifrost':
        assert get_attribute(tubes, 'NX_class') == 'NXdetector'
        assert find_child(tubes, 'data') is not None
    else:
        # No BIFROST translator in play: a placed but untranslated component, and
        # crucially not BIFROST's detector topic or ICD pixel numbering
        assert get_attribute(tubes, 'NX_class') == 'NXcoordinate_system'
        assert find_child(tubes, 'data') is None

