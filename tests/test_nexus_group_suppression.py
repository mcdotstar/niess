"""Many McCode instances collapsing into one NeXus node.

Some niess components cannot be expressed as a single McCode component -- a
multi-opening chopper is built as several ``DiskChopper`` instances. NeXus wants one
``NXdisk_chopper`` for the physical device, so one instance builds the merged node and
the rest are suppressed.

This needs no new mechanism: it is the registry's ``role`` tier, dispatching on niess
provenance rather than the McCode component type, plus the walk distinguishing "no
translator registered" (fall back to a guessed class) from "a translator ran and
returned ``None``" (emit nothing).
"""
import pytest

from niess.nexus.nodes import find_child, get_attribute

GROUP_ID = 'chopper_pack_3'

INSTR = """DEFINE INSTRUMENT group_suppression_test(dummy=0)
TRACE
COMPONENT origin = Arm() AT (0, 0, 0) ABSOLUTE
COMPONENT pack_0 = DiskChopper(theta_0=10, radius=0.35, nu=14, phase=0) AT (0, 0, 5) RELATIVE origin
COMPONENT pack_1 = DiskChopper(theta_0=20, radius=0.35, nu=14, phase=120) AT (0, 0, 5.001) RELATIVE origin
COMPONENT pack_2 = DiskChopper(theta_0=30, radius=0.35, nu=14, phase=240) AT (0, 0, 5.002) RELATIVE origin
COMPONENT sample = Arm() AT (0, 0, 10) RELATIVE origin
END
"""


@pytest.fixture
def instr():
    """A three-instance chopper pack, tagged as one NeXus group."""
    from mccode_antlr.loader import parse_mcstas_instr
    from niess.provenance import add_niess_metadata

    parsed = parse_mcstas_instr(INSTR)
    for index, name in enumerate(('pack_0', 'pack_1', 'pack_2')):
        instance = next(c for c in parsed.components if c.name == name)
        add_niess_metadata(
            instance,
            source_type='niess.components.chopper.MultiOpeningChopper',
            source_name=name,
            # Roles by explicit tag, never by position in instr.components
            role='disc-opening-primary' if index == 0 else 'disc-opening-member',
            extra={
                'disc_group_id': GROUP_ID,
                'disc_group_index': index,
            },
        )
    return parsed


@pytest.fixture
def registry():
    """A registry that folds a tagged group into one node."""
    from niess.nexus.via_instr import component_body
    from niess.nexus.nodes import dataset
    from niess.nexus.via_instr.registry import NiessNexusRegistry

    reg = NiessNexusRegistry()

    @reg.register_role('disc-opening-member')
    def suppress(t):
        return None

    @reg.register_role('disc-opening-primary')
    def multi_opening_chopper(t):
        # Reads every sibling's own parameters -- the whole instrument is reachable
        siblings = t.siblings_in_group()
        edges = []
        for sibling in siblings:
            theta = float(sibling.get_parameter('theta_0').value.value)
            phase = float(sibling.get_parameter('phase').value.value)
            edges.extend([phase - theta / 2, phase + theta / 2])
        return component_body('NXdisk_chopper', [
            dataset('slits', len(siblings)),
            dataset('slit_edges', edges, dtype='double', attrs={'units': 'degrees'}),
        ])

    # Everything else keeps the stock translators
    for name in ('Arm',):
        assert reg.resolve_builder is not None, name
    return reg


@pytest.fixture
def structure(instr, registry):
    from niess.nexus.via_instr import to_nexus_structure
    return to_nexus_structure(instr, origin='sample', registry=registry)


def instrument_of(structure):
    return structure['children'][0]['children'][0]


def test_only_the_primary_survives(structure):
    instrument = instrument_of(structure)
    assert find_child(instrument, 'pack_0') is not None
    assert find_child(instrument, 'pack_1') is None
    assert find_child(instrument, 'pack_2') is None


def test_suppressed_instances_are_not_replaced_by_a_fallback(structure):
    """Suppression must emit nothing at all -- not an empty NXnote placeholder."""
    names = [c.get('name') for c in instrument_of(structure)['children'] if 'name' in c]
    assert names == ['origin', 'pack_0', 'sample']


def test_the_merged_node_carries_every_siblings_openings(structure):
    chopper = find_child(instrument_of(structure), 'pack_0')

    assert get_attribute(chopper, 'NX_class') == 'NXdisk_chopper'
    assert find_child(chopper, 'slits')['config']['values'] == 3
    assert find_child(chopper, 'slit_edges')['config']['values'] == [
        -5.0, 5.0, 110.0, 130.0, 225.0, 255.0,
    ]


def test_group_members_are_ordered_by_tag_not_by_declaration(instr, registry):
    """Reordering the instances must not reorder the merged node's content."""
    from niess.nexus.via_instr import to_nexus_structure

    components = list(instr.components)
    order = {name: i for i, name in enumerate(c.name for c in components)}
    reordered = [components[order[n]] for n in ('origin', 'pack_2', 'pack_1', 'pack_0', 'sample')]
    instr.components = tuple(reordered)

    structure = to_nexus_structure(instr, origin='sample', registry=registry)
    chopper = find_child(instrument_of(structure), 'pack_0')
    assert find_child(chopper, 'slit_edges')['config']['values'] == [
        -5.0, 5.0, 110.0, 130.0, 225.0, 255.0,
    ]


def test_unhandled_components_still_get_a_fallback(structure):
    """"No translator" is not "suppressed": untranslated components still appear."""
    origin = find_child(instrument_of(structure), 'origin')
    assert get_attribute(origin, 'NX_class') == 'NXcoordinate_system'
