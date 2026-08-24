"""The child protocol describes the instrument the emission actually produces.

`niess.tree` declares a node's children once, so that the traversal each consumer used
to write out for itself -- Section.to_mccode_flat, the bifrost composites, and every
add_to_graph -- can come from one place. It is only worth anything if what it walks
agrees with what gets emitted, so that is what these check.
"""
import pytest

from niess.tree import default_children, is_node, leaves, walk


@pytest.fixture(scope='module')
def teaching():
    from niess.teaching import Primary
    return Primary.from_calibration()


@pytest.fixture(scope='module')
def primary():
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    return Primary.from_calibration(primary_parameters())


@pytest.fixture(scope='module')
def tank():
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    return Tank.from_calibration(tank_parameters())


def emitted_source_types(section, name, *args):
    """The niess class behind each emitted instance, in emission order."""
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.provenance import NiessProvenance

    assembler = Assembler(name, flavor=Flavor.MCSTAS)
    section.to_mccode(assembler, *args)
    return [NiessProvenance.from_instance(c).source_type.rsplit('.', 1)[-1]
            for c in assembler.instrument.components]


# -- the walk agrees with the emission ----------------------------------------

@pytest.mark.parametrize('fixture,name', [('teaching', 'teaching'), ('primary', 'bifrost')])
def test_leaves_are_the_emitted_components_in_order(request, fixture, name):
    """One leaf, one component, same order, same class -- for the sections that are 1:1.

    This is the protocol's real acceptance test. A traversal that agreed on the count
    but not the order, or picked up a value object as a component, fails here.
    """
    section = request.getfixturevalue(fixture)
    walked = [type(node).__name__ for _, node in leaves(section)]
    assert walked == emitted_source_types(section, name)


def test_tank_is_deliberately_finer_than_its_emission(tank):
    """The tank is the exception, and it is the interesting one.

    Analyzer collapses 7-9 Crystal blades into one Monochromator_Rowland and Triplet
    collapses 3 He3Tube into one Detector_tubes, so the tree is finer than the McStas
    instrument by design. Keeping the blades and tubes walkable is the point -- a
    translator that wants the real tube positions can have them.
    """
    import collections
    kinds = collections.Counter(type(node).__name__ for _, node in leaves(tank))
    assert kinds == {'Crystal': 369, 'He3Tube': 135, 'RadialFilterCollimator': 9,
                     'He3Monitor': 1}
    assert sum(kinds.values()) == 514


def test_the_composites_have_the_children_we_think_they_do(tank):
    assert [label for label, _ in tank.__niess_children__()] == \
           ['monitor'] + [f'channels[{i}]' for i in range(9)]
    channel = tank.channels[0]
    assert [label for label, _ in channel.__niess_children__()] == \
           ['radial_filter_collimator'] + [f'pairs[{i}]' for i in range(5)]
    assert [label for label, _ in channel.pairs[0].__niess_children__()] == \
           ['analyzer', 'detector']


# -- data is not a child ------------------------------------------------------

def test_a_variable_field_is_data(tank):
    """Triplet.resistances is a scipp Variable, not a thing in the beam."""
    triplet = tank.channels[0].pairs[0].detector
    labels = [label for label, _ in triplet.__niess_children__()]
    assert labels == ['tubes[0]', 'tubes[1]', 'tubes[2]']
    assert 'resistances' not in labels


def test_a_string_field_is_data(primary):
    """SegmentedGuide.name is a str; its segments are the children."""
    guides = primary.curved.unit_3_curved
    labels = [label for label, _ in guides.__niess_children__()]
    assert labels and all(label.startswith('segments[') for label in labels)


def test_elliptic_guide_reports_no_children(primary):
    """Its two PartialEllipse fields are a cross-section, not components."""
    from niess.components.guide import EllipticGuide, PartialEllipse

    guide = primary.compressor.nboa
    assert isinstance(guide, EllipticGuide)
    assert is_node(guide.horizontal) and isinstance(guide.horizontal, PartialEllipse)
    assert guide.__niess_children__() == ()


def test_section_extras_are_not_children(teaching):
    """`_flat` is a Section extra; it is a bool, and it is not in the beam."""
    labels = [label for label, _ in teaching.__niess_children__()]
    assert '_flat' not in labels
    assert labels == ['source', 'guides', 'chopper', 'jaw', 'monitor', 'sample_origin']


def test_a_sequence_mixing_components_and_data_is_refused():
    """Silently dropping half a composite is the failure worth making loud."""
    import msgspec
    from niess.components.component import Base

    class Odd(Base):
        items: list

    with pytest.raises(TypeError, match='mixes components with data'):
        Odd(items=[Base(), 'not a component']).__niess_children__()


# -- paths --------------------------------------------------------------------

def test_walk_paths_identify_a_node_without_naming_it(tank):
    """The path is what replaces the f-strings each composite used to rebuild."""
    found = {path: node for path, node in walk(tank)}
    blade = found[('channels[2]', 'pairs[0]', 'analyzer', 'blades[3]')]
    assert blade is tank.channels[2].pairs[0].analyzer.blades[3]


def test_walk_yields_the_root_first(teaching):
    (first_path, first_node), = [next(iter(walk(teaching)))]
    assert first_path == ()
    assert first_node is teaching
