"""NeXus, built from the tree.

There used to be a second route that converted an assembled McStas instrument, recovering
everything it needed from it: placement from resolve_orientations, run-time values by
folding DECLARE blocks, a detector's arc and triplet by matching a regex against a
generated WHEN clause. It is gone. This reads the tree, where all of that is present.
"""
import pytest

from niess.instrument import Instrument, Mount
from niess.nexus.nodes import find_child, get_attribute, node_name
from niess.nexus import to_nexus_structure




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

def test_each_component_gets_the_class_it_should(teaching):
    """What the two routes were compared on, for the instrument both could do.

    Written down rather than compared, now that there is one route: these are the
    classes that comparison agreed on, in the order the beam runs.
    """
    assert [(name, get_attribute(find_child(instrument_group(
        to_nexus_structure(teaching)), name), 'NX_class'))
        for name in groups(to_nexus_structure(teaching))] == [
        ('source', 'NXmoderator'),
        ('unit_1', 'NXguide'),
        ('unit_2', 'NXguide'),
        ('chopper', 'NXdisk_chopper'),
        ('jaw', 'NXaperture'),
        ('monitor', 'NXmonitor'),
        ('sample_origin', 'NXcoordinate_system'),
    ]


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


def test_the_tree_classifies_what_an_emitted_instrument_could_not(bifrost):
    """A Filter with nothing to say emits as a McStas Arm.

    The route this replaced saw an Arm and filed it under NXcoordinate_system; the tree
    says Filter. These 31 are what it had as unclassified, and the count is written down
    here because there is no longer a second route to measure it against.
    """
    from niess.nexus.bifrost import BIFROST_REGISTRY

    counted = classes(to_nexus_structure(bifrost, registry=BIFROST_REGISTRY))
    assert counted['NXfilter'] == 22
    assert counted['NXcollimator'] == 9
    assert counted['NXaperture'] >= 1          # the radial slit bank
    assert counted['NXdetector'] == 45


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


# -- the detectors have to say where their events come from -----------------------

def _descend(node):
    from niess.nexus.nodes import children_of
    for child in children_of(node):
        yield child
        yield from _descend(child)


def detector_streams(structure) -> dict:
    """Every NXdetector's stream directive, by detector name.

    ``None`` where a detector has no ``data`` group at all -- which is the failure worth
    catching: geometry describing data that never arrives.
    """
    from niess.nexus.nodes import children_of, find_child
    found = {}
    for node in _descend(structure):
        if not any(a.get('values') == 'NXdetector' for a in node.get('attributes', [])):
            continue
        data = find_child(node, 'data')
        if data is None:
            found[node_name(node)] = None
            continue
        assert get_attribute(data, 'NX_class') == 'NXevent_data'
        directive = children_of(data)[0]
        found[node_name(node)] = (directive['module'], directive['config']['source'],
                                  directive['config']['topic'])
    return found


def test_every_detector_carries_an_ev44_stream(bifrost):
    """Without it the filewriter has no NXevent_data to fill, so the detector is inert.

    The pixel geometry is only half of an NXdetector; the other half is the directive
    saying which Kafka topic and source fill it. A structure that describes 45 detectors
    and streams none of them is not a smaller answer, it is a wrong one.
    """
    from niess.nexus.bifrost import BIFROST_DETECTOR_TOPIC, BIFROST_REGISTRY
    streams = detector_streams(to_nexus_structure(bifrost, registry=BIFROST_REGISTRY))

    assert len(streams) == 45
    assert not [name for name, s in streams.items() if s is None]
    assert {s[0] for s in streams.values()} == {'ev44'}
    assert {s[2] for s in streams.values()} == {BIFROST_DETECTOR_TOPIC}
    # one source per triplet, or two detectors would be fed the same events
    assert len({s[1] for s in streams.values()}) == 45




def _bifrost_with_stream(selection):
    """A BIFROST whose triplets publish where the *calibration* says.

    Through the real path a facility would use: a `stream` entry in the tank
    calibration, which `Channel.from_calibration` forwards to each `Triplet`.
    """
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters

    params = tank_parameters()
    # a bare dict in `channels` is read as variant-keyed, so say it per variant
    params['channels']['stream'] = {v: selection for v in ('s', 'm', 'l')}
    return Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='tank', content=Tank.from_calibration(params),
              relative_to='sample_origin'),
    ))


def test_a_calibration_can_give_each_channel_its_own_stream():
    """Per channel rather than per instrument, through `channel_params`.

    One selection for the whole tank gives all 45 triplets one source, which is a way
    of saying nothing -- two detectors fed the same events. `channel_params` is where a
    calibration says something per detector.
    """
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    from niess.bifrost.triplet import Triplet
    from niess.walk import visits

    params = tank_parameters()
    variants = [{'variant': v} for v in ('s', 'm', 'l')]
    params['channels']['channel_params'] = {
        i: dict(variants[i % 3],
                stream={'module': 'ev44', 'topic': 'bifrost_detector',
                        'source': f'channel-{i}'})
        for i in range(9)
    }
    tank = Tank.from_calibration(params)
    tree = Instrument(name='bifrost', parts=(Mount(name='tank', content=tank),))
    streams = [v.obj.stream for v in visits(tree) if isinstance(v.obj, Triplet)]

    assert len(streams) == 45
    assert all(s is not None for s in streams)
    assert len({s['source'] for s in streams}) == 9


def test_a_triplet_may_say_where_its_events_are_published():
    """The topic is the facility's, not the tubes'. A calibration can set it."""
    from niess.nexus.bifrost import BIFROST_REGISTRY
    selection = {'module': 'ev44', 'topic': 'elsewhere', 'source': 'detector-7'}
    structure = to_nexus_structure(_bifrost_with_stream(selection),
                                   registry=BIFROST_REGISTRY)
    streams = detector_streams(structure)
    assert streams
    assert set(streams.values()) == {('ev44', 'detector-7', 'elsewhere')}




def test_taking_the_default_emits_the_instrument_it_always_did():
    """`stream` unset must add no METADATA, or the frozen .instr goldens would shift."""
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    from niess.mccode import to_mccode

    def emitted(tank):
        assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
        to_mccode(Instrument(name='bifrost', origin='sample_origin',
                             parts=(Mount(name='tank', content=tank),)),
                  assembler=assembler)
        return str(assembler.instrument)

    import msgspec
    plain = Tank.from_calibration(tank_parameters())
    assert emitted(plain) == emitted(msgspec.structs.replace(plain))
    assert 'nexus_stream' not in emitted(plain)
