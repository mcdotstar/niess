"""NeXus built from the tree instead of from an emitted McStas instrument.

`niess.nexus.via_instr` converts an assembled instrument and recovers everything it needs
from it:
placement from resolve_orientations, run-time values by folding DECLARE blocks, a
detector's arc and triplet by matching a regex against a generated WHEN clause. This
reads the tree, where all of that is simply present.
"""
import pytest

from niess.instrument import Instrument, Mount
from niess.nexus.nodes import find_child, get_attribute, node_name
from niess.nexus import to_nexus_structure



def test_the_two_routes_are_two_functions():
    """The guard on every comparison here: they must not have become the same one.

    `niess.nexus.to_nexus_structure` reads the tree and `niess.nexus.via_instr`'s reads an
    emitted instrument. Comparing a route against itself would pass while asserting
    nothing, and the two have lived under the same name before.
    """
    from niess.nexus import to_nexus_structure as from_tree
    from niess.nexus.via_instr import to_nexus_structure as from_instrument
    assert from_tree is not from_instrument

def instrument_group(structure):
    return structure['children'][0]['children'][0]


def groups(structure):
    return [node_name(c) for c in instrument_group(structure)['children']
            if c.get('type') == 'group']


def value(node, name):
    return find_child(node, name)['config']['values']


@pytest.fixture(scope='module')
def teaching():
    from niess.teaching import Primary
    return Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration()),
    ))


@pytest.fixture(scope='module')
def multi_opening():
    """A disc whose openings are neither identical nor evenly spaced."""
    from scipp import array, scalar, vector
    from scipp.spatial import rotations_from_rotvecs
    from niess.components import DiscChopper, Section

    disc = DiscChopper.from_calibration({
        'name': 'pack', 'position': vector([0, 0, 5.0], unit='m'),
        'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
        'radius': scalar(0.35, unit='m'), 'height': scalar(0.06, unit='m'),
        'frequency': scalar(14.0, unit='Hz'),
        'top_dead_center': scalar(15.0, unit='deg'),
        'beam_position': scalar(90.0, unit='deg'),
        'windows': array(values=[10., 30., 100., 140., 350., 370.],
                         dims=['edges'], unit='deg'),
    })

    class Chopped(Section):
        pack: DiscChopper
        _flat: bool = True

    return Chopped(pack=disc)


# -- the same instrument, classified the same way -----------------------------

def test_the_same_components_get_the_same_nexus_classes(teaching):
    """Against the instrument-reading path, for the instrument both can do."""
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.nexus.via_instr import to_nexus_structure as from_instrument
    from niess.teaching import Primary

    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    Primary.from_calibration().to_mccode(assembler)
    old = from_instrument(assembler.instrument, origin='sample_origin')
    new = to_nexus_structure(teaching)

    assert groups(new) == groups(old)
    for name in groups(new):
        assert get_attribute(find_child(instrument_group(new), name), 'NX_class') == \
               get_attribute(find_child(instrument_group(old), name), 'NX_class'), name


# -- the case the refactor exists for -----------------------------------------

def test_a_multi_opening_disc_is_one_disc(multi_opening):
    """It never came apart, so nothing has to put it back together.

    McStas cannot describe a disc whose openings are neither identical nor evenly
    spaced, so it becomes one component per opening. `niess.nexus.via_instr` reassembles it from
    group tags written into METADATA on each of those components -- tags invented for
    this, and since read by three targets. Reading the tree, the disc is a disc.
    """
    structure = to_nexus_structure(
        Instrument(name='chopped', parts=(Mount(name='s', content=multi_opening),)))
    assert groups(structure) == ['pack']

    disc = find_child(instrument_group(structure), 'pack')
    assert get_attribute(disc, 'NX_class') == 'NXdisk_chopper'
    assert value(disc, 'slits') == 3
    assert value(disc, 'slit_edges') == [10., 30., 100., 140., 350., 370.]
    assert value(disc, 'top_dead_center') == 15.0
    assert value(disc, 'beam_position') == 90.0


def test_it_agrees_with_what_the_reassembly_produces(multi_opening):
    """The values are the same; only the work needed to get them differs."""
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.nexus.via_instr import to_nexus_structure as from_instrument

    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    multi_opening.to_mccode(assembler)
    old = find_child(instrument_group(
        from_instrument(assembler.instrument, origin='pack_slit_0')), 'pack')
    new = find_child(instrument_group(to_nexus_structure(
        Instrument(name='chopped',
                   parts=(Mount(name='s', content=multi_opening),)))), 'pack')

    for field in ('slits', 'slit_edges', 'top_dead_center', 'beam_position'):
        assert value(new, field) == value(old, field), field

    # what it took the other way: three components, each carrying a tag saying which
    # disc it is part of and in what order
    assert len(assembler.instrument.components) == 3
    tagged = [m for c in assembler.instrument.components for m in c.metadata
              if m.name == 'niess_provenance']
    assert len(tagged) == 3


# -- placement ----------------------------------------------------------------

def test_placement_hangs_from_the_frames_the_tree_declares(teaching):
    """No absolute orientations resolved and no origin subtracted back out."""
    structure = to_nexus_structure(teaching)
    chopper = find_child(instrument_group(structure), 'chopper')
    transformations = find_child(chopper, 'transformations')
    assert transformations is not None
    assert get_attribute(transformations, 'NX_class') == 'NXtransformations'
    assert find_child(chopper, 'depends_on') is not None


def test_a_thing_at_the_origin_needs_no_transformation(teaching):
    structure = to_nexus_structure(teaching)
    source = find_child(instrument_group(structure), 'source')
    assert find_child(source, 'transformations') is None


# -- how a translator is written ----------------------------------------------

def test_a_class_may_carry_its_own_nexus_hook():
    """Both idioms work for every target; which reads better depends on the target."""
    from niess.dispatch import ClassHooks
    from niess.nexus import NiessNexusRegistry

    class Odd:
        def __nexus_leaf__(self, visit):
            return None

    resolved = NiessNexusRegistry().resolve_for_object(Odd())
    assert isinstance(resolved, ClassHooks)


def test_registering_wins_over_the_class():
    from niess.nexus import NEXUS_REGISTRY, NiessNexusRegistry
    from niess.components.chopper import DiscChopper

    scoped = NiessNexusRegistry(parent=NEXUS_REGISTRY)
    scoped.register(DiscChopper)('mine')
    assert scoped.resolve_for_object.__self__ is scoped


# -- BIFROST ------------------------------------------------------------------

@pytest.fixture(scope='module')
def bifrost():
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    return Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin'),
    ))


def classes(structure):
    import collections
    return collections.Counter(
        get_attribute(g, 'NX_class') for g in instrument_group(structure)['children']
        if g.get('type') == 'group')


def test_bifrost_converts(bifrost):
    from niess.nexus.bifrost import BIFROST_REGISTRY
    counted = classes(to_nexus_structure(bifrost, registry=BIFROST_REGISTRY))
    assert counted['NXcrystal'] == 45      # one per arm, not one per blade
    assert counted['NXdetector'] == 45     # one per arm, not one per tube
    assert counted['NXguide'] == 119
    assert counted['NXdisk_chopper'] == 6
    assert counted['NXslit'] == 1          # the radial slit bank
    assert sum(counted.values()) == 358    # one group per emitted component


def test_reading_the_tree_classifies_more_than_reading_the_instrument(bifrost):
    """The windows and collimators are recognisable here and were not before.

    A Filter with nothing to say emits as a McStas Arm, so an instrument-reading
    converter sees an Arm and files it under NXcoordinate_system. The tree says Filter.
    """
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.nexus.via_instr import to_nexus_structure as from_instrument
    from niess.nexus.via_instr.bifrost import BIFROST_REGISTRY as INSTRUMENT_REGISTRY
    from niess.nexus.bifrost import BIFROST_REGISTRY
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)
    Tank.from_calibration(tank_parameters()).to_mccode(assembler, 'sample_origin')
    old = classes(from_instrument(assembler.instrument, origin='sample_origin',
                                  registry=INSTRUMENT_REGISTRY))
    new = classes(to_nexus_structure(bifrost, registry=BIFROST_REGISTRY))

    # what both agree on
    for shared in ('NXcrystal', 'NXdetector', 'NXguide', 'NXdisk_chopper',
                   'NXmonitor', 'NXaperture', 'NXmoderator'):
        assert old[shared] == new[shared], shared

    assert old['NXfilter'] == 0 and new['NXfilter'] == 22
    assert old['NXcollimator'] == 0 and new['NXcollimator'] == 9
    # and the 31 that gains, plus the radial slit bank, are what it had as unclassified
    assert old['NXcoordinate_system'] - new['NXcoordinate_system'] == 32


def test_arc_and_triplet_come_from_the_tree(bifrost):
    """Not from a regex over a generated WHEN clause."""
    from niess.nexus.bifrost import BIFROST_REGISTRY, icd_pixel

    structure = to_nexus_structure(bifrost, registry=BIFROST_REGISTRY)
    detector = find_child(instrument_group(structure), 'channel_3_2_triplet')
    numbers = value(detector, 'detector_number')
    # channel 3 is cassette index 2, arm 2 is arc index 1
    resolution = len(numbers[0])
    assert numbers[0][0] == icd_pixel(resolution, 1, 2, 0, 0)


def test_the_radial_slit_bank_is_an_aperture(bifrost):
    """It was emitted by Tank's McStas hook, so only McStas could see it.

    It is a real aperture that happens to be used for bookkeeping -- the emitted
    component reports which opening a neutron passed and everything downstream is gated
    on that -- rather than bookkeeping that happens to look like an aperture.
    """
    from niess.nexus.bifrost import BIFROST_REGISTRY

    structure = to_nexus_structure(bifrost, registry=BIFROST_REGISTRY)
    slits = find_child(instrument_group(structure), 'slits')
    assert get_attribute(slits, 'NX_class') == 'NXslit'
    assert len(value(slits, 'angles')) == 10       # nine channels and the monitor
    # both knobs a calibration run sweeps are links, not numbers a run could contradict
    assert get_attribute(find_child(slits, 'distance'), 'NX_class') == 'NXlog'
    assert get_attribute(find_child(slits, 'offset'), 'NX_class') == 'NXlog'


def test_the_frozen_structure_is_unchanged(bifrost):
    from .baseline import NEXUS_STRUCTURES, frozen_json, nexus_structures
    assert nexus_structures() == frozen_json(NEXUS_STRUCTURES)


# -- run-time values and streams ----------------------------------------------

def test_a_knob_is_a_link_not_a_number(teaching):
    """A chopper's speed is not something the instrument has; it is something a run sets.

    So the file says where to read it. `niess.nexus.via_instr` decides this by folding a McCode
    expression and seeing whether an instrument parameter survives; here the chopper
    names the knob it declared.
    """
    structure = to_nexus_structure(teaching)
    chopper = find_child(instrument_group(structure), 'chopper')
    for field in ('rotation_speed', 'delay'):
        linked = find_child(chopper, field)
        assert get_attribute(linked, 'NX_class') == 'NXlog', field
        assert linked['children'], f'{field} links nothing'


def test_a_driven_edge_is_a_link(teaching):
    """A jaw's edges are knobs; a plain aperture's opening is not."""
    structure = to_nexus_structure(teaching)
    jaw = find_child(instrument_group(structure), 'jaw')
    assert get_attribute(find_child(jaw, 'left'), 'NX_class') == 'NXlog'
    assert get_attribute(find_child(jaw, 'right'), 'NX_class') == 'NXlog'
    # its height is fixed, so it stays a number
    assert find_child(jaw, 'y_gap')['config']['values'] > 0


def test_a_monitor_carries_its_stream(teaching):
    """Histograms by default, which is what a frame monitor has always done."""
    structure = to_nexus_structure(teaching)
    monitor = find_child(instrument_group(structure), 'monitor')
    data = find_child(monitor, 'data')
    assert get_attribute(data, 'NX_class') == 'NXdata'
    assert data['children'][0]['module'] == 'da00'


def test_the_instrument_chooses_the_protocol():
    """Events or histograms is a property of the setup, not of the monitor type."""
    from msgspec.structs import replace
    from niess.teaching import Primary

    primary = Primary.from_calibration()
    events = replace(primary.monitor,
                     stream={'module': 'ev44', 'topic': 'teaching_events',
                             'source': 'monitor'})
    primary = replace(primary, monitor=events)
    structure = to_nexus_structure(Instrument(
        name='teaching', origin='sample_origin',
        parts=(Mount(name='primary', content=primary),)))

    data = find_child(find_child(instrument_group(structure), 'monitor'), 'data')
    assert get_attribute(data, 'NX_class') == 'NXevent_data'
    assert data['children'][0]['module'] == 'ev44'
    assert data['children'][0]['config']['topic'] == 'teaching_events'


def test_a_linked_log_deep_links_rather_than_linking_the_group(teaching):
    """Why it is a group of links and not one link to a group.

    A `link` module pointing at the NXlog itself would give the file the value, but
    nothing could be added to it. Mirroring each dataset instead leaves the group ours,
    so it can carry attributes the original has no reason to have -- which it must when
    it is part of an NXtransformations chain and needs a transformation_type and a
    vector alongside the value.
    """
    structure = to_nexus_structure(teaching)
    speed = find_child(find_child(instrument_group(structure), 'chopper'),
                       'rotation_speed')

    assert get_attribute(speed, 'NX_class') == 'NXlog'
    assert speed['type'] == 'group', 'a group of links, not a link to a group'

    modules = {c['module'] for c in speed['children']}
    assert modules == {'link'}
    sources = {c['config']['source'] for c in speed['children']}
    assert '/entry/parameters/chopperspeed/value' in sources
    assert '/entry/parameters/chopperspeed/time' in sources

    # and the group takes attributes of its own
    assert get_attribute(speed, 'units') == 'Hz'


def test_a_linked_log_can_carry_transformation_attributes(teaching):
    """The case the deep links exist for.

    Nothing in niess builds a driven transformation yet -- a tank rotated by a4 will --
    so this checks the mechanism rather than a caller of it.
    """
    from niess.nexus import NexusContext

    context = NexusContext(instrument=teaching)
    node = context.linked_log('rotation', 'a4', attrs={
        'units': 'degrees', 'transformation_type': 'rotation',
        'vector': [0.0, 1.0, 0.0], 'depends_on': '.'})

    assert get_attribute(node, 'transformation_type') == 'rotation'
    assert get_attribute(node, 'vector') == [0.0, 1.0, 0.0]
    assert {c['module'] for c in node['children']} == {'link'}
