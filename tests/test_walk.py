"""The walk: one pass over the tree, for whatever is being built from it.

Nothing uses it yet -- the targets move onto it later. What matters here is that it
visits the right nodes in the right order, and that the names and frames it derives are
the ones the emission actually uses, because that is what the McStas translator will
read instead of recomputing.
"""
import pytest

from niess.components.component import Component
from niess.instrument import Instrument, Mount
from niess.walk import SKIP, Context, Visit, visits, walk


@pytest.fixture(scope='module')
def parts():
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    return (Primary.from_calibration(primary_parameters()),
            Tank.from_calibration(tank_parameters()))


@pytest.fixture(scope='module')
def bifrost(parts):
    primary, tank = parts
    return Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=primary),
        Mount(name='tank', content=tank, relative_to='sample_origin'),
    ))


@pytest.fixture(scope='module')
def emitted_names(parts):
    """The instrument built the old way, for the walk to be checked against."""
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)
    Tank.from_calibration(tank_parameters()).to_mccode(assembler, 'sample_origin')
    return [c.name for c in assembler.instrument.components]


@pytest.fixture(scope='module')
def seen(bifrost):
    return {visit.id: visit for visit in visits(bifrost)}


# -- the root -----------------------------------------------------------------

def test_the_instrument_is_one_object(bifrost):
    from niess.tree import leaves
    assert [label for label, _ in bifrost.__niess_children__()] == ['primary', 'tank']
    assert len(leaves(bifrost)) == 772  # 158 primary + 614 tank


def test_the_whole_instrument_has_one_connected_flow(bifrost):
    """Which is the point of having a root at all: the tank hangs off the primary."""
    import networkx as nx

    graph = bifrost.to_graph()
    assert nx.number_weakly_connected_components(graph) == 1
    # the tank's entry is its radial slits, which is where the ten branches start
    assert list(graph.successors('primary/sample_origin')) == ['tank/slits']
    assert len(list(graph.successors('tank/slits'))) == 10


def test_of_builds_from_keywords():
    from niess.teaching import Primary
    instrument = Instrument.of('teaching', primary=Primary.from_calibration())
    assert [m.name for m in instrument.parts] == ['primary']
    assert instrument.parts[0].relative_to is None


# -- names --------------------------------------------------------------------

def test_every_derived_component_name_is_one_the_emission_uses(bifrost, emitted_names):
    """The acceptance test for the naming rule.

    169 of BIFROST's 358 components have a niess Component behind them; the other 189
    are the coordinate frames and the two aggregates per arm, neither of which is a
    Component and both of which the McStas translator names for itself.
    """
    walked = [visit.name for visit in visits(bifrost)
              if isinstance(visit.obj, Component) and not visit.obj.__niess_children__()]
    assert len(walked) == 169
    assert len(set(walked)) == 169, 'names must be unique across an instrument'
    assert set(walked) <= set(emitted_names)


@pytest.mark.parametrize('path,expected', [
    ('primary/closing/jaw_1', 'jaw_1'),
    ('primary/compressor/nboa', 'nboa'),
    ('tank/monitor', 'elastic_monitor'),
    ('tank/channels[2]/radial_filter_collimator', 'channel_3_radial_filter_collimator'),
])
def test_names_are_built_from_what_the_ancestors_contribute(seen, path, expected):
    assert seen[path].name == expected


def test_sections_contribute_nothing_to_a_name(seen):
    """A guide three sections deep is still called what it was calibrated as."""
    visit = seen['primary/closing/jaw_1']
    assert visit.prefix == ''
    assert [v.own_label for v in _ancestors(visit)] == [None, None, None]


def _ancestors(visit):
    found = []
    node = visit.parent
    while node is not None:
        found.append(node)
        node = node.parent
    return found


def test_a_composite_names_what_is_inside_it(seen):
    """channel_3_1, which an analyzer and a detector then suffix differently."""
    analyzer = seen['tank/channels[2]/pairs[0]/analyzer']
    assert analyzer.prefix == 'channel_3_1'
    assert analyzer.emit_name('monochromator') == 'channel_3_1_monochromator'
    detector = seen['tank/channels[2]/pairs[0]/detector']
    assert detector.emit_name('triplet') == 'channel_3_1_triplet'


def test_ancestor_replaces_reading_indices_out_of_generated_c(seen):
    """niess.nexus.bifrost recovers arc and triplet by regex over a WHEN clause."""
    from niess.bifrost.arm import Arm
    from niess.bifrost.channel import Channel

    visit = seen['tank/channels[2]/pairs[3]/detector']
    assert visit.ancestor(Channel).index == 2
    assert visit.ancestor(Arm).index == 3
    assert visit.ancestor(Channel).own_label == 'channel_3'


# -- frames -------------------------------------------------------------------

def test_each_piece_hangs_where_its_mount_says(seen):
    """The primary is in global coordinates; the tank is described about the sample."""
    assert seen['primary/closing/jaw_1'].frame is None
    assert seen['tank/monitor'].frame == 'sample_origin'
    # inside the tank a declared frame takes over: the cassette, then the arm's own
    assert seen['tank/channels[2]/cassette'].frame == 'sample_origin'
    assert seen['tank/channels[2]/radial_filter_collimator'].frame == \
        'tank/channels[2]/cassette'
    assert seen['tank/channels[2]/pairs[0]/analyzer'].frame == \
        'tank/channels[2]/pairs[0]/analyzer_point'


def test_the_origin_is_a_property_of_the_instrument(bifrost):
    """Targets each guess at this today; niess.nexus warns when it cannot find one."""
    assert Context(instrument=bifrost).origin == 'sample_origin'


# -- order and events ---------------------------------------------------------

def test_visits_are_depth_first_in_declaration_order(bifrost):
    order = [visit.id for visit in visits(bifrost)]
    assert order[0] == ''
    assert order[1] == 'primary'
    assert order[2] == 'primary/source'
    assert order.index('primary/sample_origin') < order.index('tank')
    assert order.index('tank/monitor') < order.index('tank/channels[0]')


def test_enter_and_exit_bracket_the_children(bifrost):
    from niess.dispatch import NiessRegistry
    from niess.bifrost.channel import Channel

    events = []
    registry = NiessRegistry()

    class Record:
        @staticmethod
        def enter(visit):
            events.append(('enter', visit.id))
            return 'token'

        @staticmethod
        def exit(visit, entered):
            events.append(('exit', visit.id, entered))

    registry.register(Channel)(Record)
    walk(bifrost, registry)

    assert events[0] == ('enter', 'tank/channels[0]')
    assert events[1] == ('exit', 'tank/channels[0]', 'token')
    assert len(events) == 18  # nine channels, entered and left


def test_skip_stops_the_walk_descending(bifrost):
    """An analyzer is seven blades and one component; its translator owns the blades."""
    from niess.dispatch import NiessRegistry
    from niess.bifrost.analyzer import Analyzer
    from niess.components.crystals import Crystal

    seen_blades = []
    registry = NiessRegistry()

    class Consume:
        @staticmethod
        def enter(visit):
            return SKIP

    class CountBlades:
        @staticmethod
        def leaf(visit):
            seen_blades.append(visit.id)

    registry.register(Crystal)(CountBlades)
    walk(bifrost, registry)
    assert len(seen_blades) == 369

    seen_blades.clear()
    registry.register(Analyzer)(Consume)
    walk(bifrost, registry)
    assert seen_blades == []


# -- the tree is not damaged by being built ------------------------------------

def test_building_does_not_rename_anything_in_the_tree(parts):
    """to_mccode used to assign the emitted name back onto the filter it came from.

    A tank that had been built once no longer serialised to what it was calibrated
    with, and anything deriving a name from the tree got the prefix twice over.
    """
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler

    _, tank = parts
    before = [channel.radial_filter_collimator.name for channel in tank.channels]
    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    assembler.component('sample_origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    tank.to_mccode(assembler, 'sample_origin')

    assert [c.radial_filter_collimator.name for c in tank.channels] == before
    assert before == ['radial_filter_collimator'] * 9
    assert 'channel_1_radial_filter_collimator' in \
           [c.name for c in assembler.instrument.components]


# -- resolving a translator for an object -------------------------------------

def test_resolution_walks_the_mro(parts):
    """Registering against Component catches anything not asking for more."""
    from niess.components.aperture import Jaw
    from niess.components.component import Component
    from niess.dispatch import NiessRegistry

    registry = NiessRegistry()
    registry.register(Component)('generic')
    _, tank = parts
    jaw = Jaw.from_calibration({
        'name': 'j', 'position': tank.monitor.position,
        'orientation': tank.monitor.orientation,
        'width': tank.monitor.radius, 'height': tank.monitor.radius,
    })
    assert registry.resolve_for_object(jaw) == 'generic'

    registry.register(Jaw)('specific')
    assert registry.resolve_for_object(jaw) == 'specific', 'the closer class wins'


def test_resolution_falls_through_to_a_parent(parts):
    from niess.bifrost.channel import Channel
    from niess.dispatch import NiessRegistry

    base = NiessRegistry()
    base.register(Channel)('from the parent')
    child = NiessRegistry(parent=base)
    _, tank = parts
    assert child.resolve_for_object(tank.channels[0]) == 'from the parent'

    child.register(Channel)('from the child')
    assert child.resolve_for_object(tank.channels[0]) == 'from the child'


def test_resolution_can_key_on_a_role(parts):
    from niess.dispatch import NiessRegistry

    registry = NiessRegistry()
    registry.register_role('physical-component')('by role')
    _, tank = parts
    assert registry.resolve_for_object(tank.monitor) == 'by role'


def test_nothing_registered_is_not_the_same_as_declining(parts):
    """The distinction the rest of niess already depends on."""
    from niess.dispatch import NiessRegistry

    _, tank = parts
    assert NiessRegistry().resolve_for_object(tank.monitor) is None


# -- mounting a piece at an angle ---------------------------------------------

def a_parameter(text):
    from mccode_antlr.common import InstrumentParameter
    return InstrumentParameter.parse(text)


def test_a_mount_can_be_turned_by_a_run_time_parameter(parts):
    """A BIFROST run turns the sample by a3 and the tank by a4.

    Neither is known when the instrument is described, so the mounting holds the
    parameter itself rather than an angle.
    """
    _, tank = parts
    a4 = a_parameter('a4/"degree" = 0.0')
    mount = Mount(name='tank', content=tank, relative_to='sample_origin',
                  rotation=(0, a4, 0))
    assert mount.is_turned()
    assert mount.parameters() == (a4,)


def test_an_unturned_mount_says_so(parts):
    _, tank = parts
    assert not Mount(name='tank', content=tank).is_turned()
    assert not Mount(name='tank', content=tank, rotation=(0, 0, 0)).is_turned()
    assert Mount(name='tank', content=tank, rotation=(0, 5.0, 0)).is_turned()


def test_a_fixed_rotation_needs_no_parameters(parts):
    _, tank = parts
    mount = Mount(name='tank', content=tank, rotation=(0, 5.0, 0))
    assert mount.parameters() == ()


def test_an_instrument_collects_what_its_mountings_need(parts):
    primary, tank = parts
    a3, a4 = a_parameter('a3/"degree" = 0.0'), a_parameter('a4/"degree" = 0.0')
    instrument = Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=primary),
        Mount(name='tank', content=tank, relative_to='sample_origin',
              rotation=(0, a4, 0)),
    ))
    assert instrument.mount_parameters() == (a4,)
    assert a3 not in instrument.mount_parameters()


def test_a_turned_mount_still_walks_and_names_the_same(parts):
    """Turning a piece is a placement, not a change of what is in it."""
    primary, tank = parts
    a4 = a_parameter('a4/"degree" = 0.0')
    turned = Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=primary),
        Mount(name='tank', content=tank, relative_to='sample_origin',
              rotation=(0, a4, 0)),
    ))
    names = {v.id: v.name for v in visits(turned)}
    assert names['tank/channels[2]/radial_filter_collimator'] == \
        'channel_3_radial_filter_collimator'
    assert {v.id: v.frame for v in visits(turned)}['tank/monitor'] == 'sample_origin'
