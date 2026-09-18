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
                     'He3Monitor': 1, 'Frame': 99}
    # the ninety-nine frames are declared nodes, not emission artefacts
    assert sum(kinds.values()) == 613


def test_the_composites_have_the_children_we_think_they_do(tank):
    assert [label for label, _ in tank.__niess_children__()] == \
           ['monitor'] + [f'channels[{i}]' for i in range(9)]
    channel = tank.channels[0]
    assert [label for label, _ in channel.__niess_children__()] == \
           ['cassette', 'radial_filter_collimator'] + [f'pairs[{i}]' for i in range(5)]
    assert [label for label, _ in channel.pairs[0].__niess_children__()] == \
           ['analyzer_point', 'analyzer', 'detector_angle', 'detector']


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


# -- particle flow ------------------------------------------------------------

def test_the_tank_has_ten_paths_out_of_the_sample(tank):
    """The case McCode cannot state, and the reason niess keeps its own graph.

    A McCode instrument is a list, so the only flow it can express is the order the
    components are declared in. A neutron leaving the sample here takes one of ten
    branches -- nine channels or the elastic monitor -- and NeXus says so through each
    group's `inputs` and `outputs`.
    """
    graph = tank.to_graph()
    roots = [node for node in graph if graph.in_degree(node) == 0]
    assert len(roots) == 1
    branches = sorted(graph.successors(roots[0]))
    assert len(branches) == 10
    assert branches == sorted(
        [f'channels[{i}]/radial_filter_collimator' for i in range(9)] + ['monitor']
    )


def test_the_elastic_monitor_is_reachable_from_the_sample(tank):
    """It used to be isolated: it was attached to `upstream`, None at the top level."""
    import networkx as nx

    graph = tank.to_graph()
    assert nx.number_weakly_connected_components(graph) == 1
    root, = [node for node in graph if graph.in_degree(node) == 0]
    assert nx.has_path(graph, root, 'monitor')


def test_the_radial_filter_comes_before_a_channels_analyzers(tank):
    """The filter is what a neutron entering a channel meets first."""
    import networkx as nx

    graph = tank.to_graph()
    filtered = 'channels[0]/radial_filter_collimator'
    for arm in range(5):
        assert nx.has_path(graph, filtered, f'channels[0]/pairs[{arm}]/analyzer')
    assert graph.in_degree(filtered) == 1


def test_a_channels_arms_are_chained_in_series(tank):
    """A neutron that is not scattered by one analyzer meets the next."""
    graph = tank.to_graph()
    chain = ['channels[3]/radial_filter_collimator']
    for arm in range(5):
        chain += [f'channels[3]/pairs[{arm}]/analyzer',
                  f'channels[3]/pairs[{arm}]/detector']
    for source, target in zip(chain, chain[1:]):
        assert graph.has_edge(source, target), f'{source} -> {target}'


def test_an_analyzer_is_one_node_however_many_blades(tank):
    """It emits one component and becomes one NeXus group; flow meets it once."""
    graph = tank.to_graph()
    assert 'channels[0]/pairs[0]/analyzer' in graph
    assert not [n for n in graph if n.startswith('channels[0]/pairs[0]/analyzer/')]
    assert not [n for n in graph if n.startswith('channels[0]/pairs[0]/detector/')]


@pytest.mark.parametrize('fixture,expected', [('teaching', 7), ('primary', 158)])
def test_a_linear_section_gives_a_linear_graph(request, fixture, expected):
    """And it can be built at all.

    Section.add_to_graph iterated __struct_fields__ rather than parts(), so it reached
    the `_flat` bool and raised AttributeError on every section carrying one -- which is
    both Primary classes. This has never run before.
    """
    import networkx as nx

    graph = request.getfixturevalue(fixture).to_graph()
    assert graph.number_of_nodes() == expected
    assert graph.number_of_edges() == expected - 1
    assert nx.number_weakly_connected_components(graph) == 1


def test_flow_nodes_are_tree_paths(tank):
    """Not the objects: Base defines __eq__ without __hash__, so it cannot be a key.

    A path also identifies a node without borrowing any one target's names for it,
    which is what lets the emitted-name rebuilding go away.
    """
    from niess.components.component import Base

    with pytest.raises(TypeError, match='unhashable'):
        hash(tank.channels[0])
    assert all(isinstance(node, str) for node in tank.to_graph())


# -- frames -------------------------------------------------------------------

def test_frames_are_declared_nodes_any_target_can_see(tank):
    """They used to exist only as a side effect of emitting McStas.

    So the only way to learn that an analyzer sits 1.19 m along its channel and rolled a
    quarter turn was to emit a McStas instrument and read it back.
    """
    from niess.components.frame import Frame

    found = {path: node for path, node in walk(tank) if isinstance(node, Frame)}
    assert len(found) == 99  # nine cassettes, two per arm
    assert ('channels[2]', 'cassette') in found
    assert ('channels[2]', 'pairs[0]', 'analyzer_point') in found
    assert ('channels[2]', 'pairs[0]', 'detector_angle') in found


def test_a_frame_is_transparent_to_flow(tank):
    """Nothing passes through it, so the things either side chain to each other."""
    graph = tank.to_graph()
    assert not [node for node in graph
                if node.endswith(('cassette', 'analyzer_point', 'detector_angle'))]
    assert graph.has_edge('channels[0]/radial_filter_collimator',
                          'channels[0]/pairs[0]/analyzer')


def test_a_declared_turn_survives_being_emitted_exactly(tank):
    """Why a frame carries axis-angle rather than a quaternion.

    Eight of BIFROST's nine cassette angles come back changed in the last bit or two
    through a quaternion, which is physically nothing and textually a different
    instrument.
    """
    for channel in tank.channels:
        cassette = dict(channel.__niess_children__())['cassette']
        assert cassette.angles() == (0.0, channel.cassette_angle.value, 0.0)

    arm = tank.channels[0].pairs[0]
    frames = dict(arm.__niess_children__())
    assert frames['detector_angle'].angles() == (0.0, arm.analyzer_theta.value, 0.0)
    assert frames['analyzer_point'].angles() == (0.0, 0.0, 90.0)


def test_a_frame_may_be_measured_from_a_sibling(tank):
    """An arm's second frame is measured from the analyzer, not from the arm.

    A detector sits at twice the Bragg angle, and the analyzer is what defines it.
    """
    frames = dict(tank.channels[0].pairs[0].__niess_children__())
    assert frames['analyzer_point'].relative_to is None
    assert frames['detector_angle'].relative_to == 'analyzer'


def test_what_sits_in_which_frame(tank):
    """Declared once, so no target has to restate the chain."""
    from niess.walk import visits
    from niess.instrument import Instrument, Mount

    instrument = Instrument(name='t', parts=(Mount(name='tank', content=tank),))
    seen = {v.id: v.frame for v in visits(instrument)}
    assert seen['tank/channels[0]/radial_filter_collimator'] == 'tank/channels[0]/cassette'
    assert seen['tank/channels[0]/pairs[0]/analyzer'] == \
        'tank/channels[0]/pairs[0]/analyzer_point'
    assert seen['tank/channels[0]/pairs[0]/detector'] == \
        'tank/channels[0]/pairs[0]/detector_angle'
