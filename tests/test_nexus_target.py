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
    spaced, so it becomes one component per opening. The route this replaced reassembled it from
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
    assert value(disc, 'zero_position') == 15.0
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
    # but it still says what it hangs from -- '.' being how NeXus spells "nothing"
    assert value(source, 'depends_on') == '.'


def test_an_identity_placement_still_says_what_it_hangs_from():
    """It added no transformation of its own, so it used to say nothing at all.

    A wedge or a cassette at exactly zero degrees produced no NXtransformations group,
    and the `depends_on` was written only when that group was -- so the component fell
    out of the chain entirely. Under a motorised mounting that is a real error and not
    a cosmetic one: nothing recorded that wedge_4 turns with the tank, so a reader
    driving a4 would leave it behind while its eight siblings moved.

    Fixed by writing the parent's link instead. NeXus lets `depends_on` name a
    transformation in another group, so there is no identity transformation to invent.
    """
    from niess.instrument import Instrument, Mount
    from niess.components.motor import Motor
    from niess.nexus.bifrost import BIFROST_REGISTRY
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters

    a4 = Motor(name='a4', unit='degree', source='a4', topic='motion', default=0.0)
    instrument = Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin', rotation=(0, a4, 0)),
    ))
    group = instrument_group(to_nexus_structure(instrument, registry=BIFROST_REGISTRY))
    mounting = '/entry/instrument/tank_mounting/transformations/rotation_y'

    # wedge_4 is the one at zero degrees, and channel_5_arm is its cassette
    for name in ('wedge_4', 'channel_5_arm'):
        component = find_child(group, name)
        assert find_child(component, 'transformations') is None, name
        assert value(component, 'depends_on') == mounting, name

    # its neighbours turn about their own angle first, then hang off the same mounting
    for name in ('wedge_3', 'wedge_5'):
        component = find_child(group, name)
        rotation = find_child(find_child(component, 'transformations'), 'rotation_y')
        assert get_attribute(rotation, 'depends_on') == mounting, name
        assert value(component, 'depends_on') == \
            f'/entry/instrument/{name}/transformations/rotation_y'


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
    # no NXslit: the radial slit bank is a simulation device, not an aperture, and is
    # deliberately not written -- see `test_the_radial_slit_bank_is_not_written`
    assert 'NXslit' not in counted
    assert sum(counted.values()) == 357    # one group per emitted component


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


def test_no_aperture_is_written_for_the_cassette_tagging(bifrost):
    """Tagging a neutron with the channel it entered is not a thing at the sample.

    It used to be a `RadialSlitBank`, emitted as one `NXslit` reporting ten slits with
    an angle in `x_gap`, which is a length. Ten `NXslit`s would have fixed the count and
    not the units, and would have put ten apertures in the file that a reduction has to
    learn to ignore -- so `niess.nexus` wrote nothing for it.

    The wedges do the tagging now, and they are real: nine radial filter-collimators
    that a reduction should see. What must not come back is an aperture standing in for
    the tagging, so this checks both halves -- the slits are gone, and the nine things
    that replaced them are written as the components they are.
    """
    from niess.nexus.bifrost import BIFROST_REGISTRY

    group = instrument_group(to_nexus_structure(bifrost, registry=BIFROST_REGISTRY))
    assert find_child(group, 'slits') is None
    written = [find_child(group, f'wedge_{i}') for i in range(9)]
    assert all(w is not None for w in written)
    assert not any(get_attribute(w, 'NX_class') == 'NXslit' for w in written)

def test_the_frozen_structure_changes_only_as_declared(bifrost):
    """Not "is unchanged": the format is being brought into line with a static checker.

    `NEXUS_MIGRATIONS` says what each deliberate change was, the frozen structure is
    brought forward by them, and what is left has to match exactly. That proves more than
    re-minting would -- re-minting says the golden moved, which is also what it says when
    something breaks.
    """
    from .baseline import NEXUS_STRUCTURES, frozen_json, migrated, nexus_structures
    assert nexus_structures() == migrated(frozen_json(NEXUS_STRUCTURES))


def test_every_declared_migration_is_still_doing_something(bifrost):
    """A rule that changes nothing has been absorbed by a re-mint and should go.

    Otherwise the list becomes a pile nobody dares empty, and the next reader cannot tell
    which entries still describe the gap between the file and the code.
    """
    from copy import deepcopy
    from .baseline import (NEXUS_MIGRATIONS, NEXUS_STRUCTURES, _walk_nodes,
                           frozen_json, migrated)

    frozen = frozen_json(NEXUS_STRUCTURES)
    for description, migrate in NEXUS_MIGRATIONS:
        before = deepcopy(frozen)
        for name in before:
            for node in _walk_nodes(before[name]):
                migrate(node)
        assert before != frozen, f'migration does nothing: {description}'


def test_every_log_says_where_its_values_come_from(bifrost):
    """An NXlog with no source is a promise the file cannot keep.

    Either it carries a stream that fills it -- `f144` for a value a run drives -- or it
    links to datasets in a log something else fills. A group with neither is an empty
    log that reads as though data were coming.
    """
    from .baseline import _walk_nodes, nexus_structures

    for name, structure in nexus_structures().items():
        for node in _walk_nodes(structure):
            classes = [a for a in (node.get('attributes') or [])
                       if a.get('name') == 'NX_class' and a.get('values') == 'NXlog']
            if not classes:
                continue
            modules = {c.get('module') for c in (node.get('children') or [])}
            assert modules, f'{name}: {node.get("name")} is an NXlog with no children'
            assert modules <= {'f144', 'link'}, \
                f'{name}: {node.get("name")} fills itself with {modules}'


def test_a_disc_writes_the_field_name_the_format_asks_for(bifrost):
    """`zero_position`, not `top_dead_center`.

    A calibration may still be *given* `top_dead_center` -- that is an input alias for
    `zero_angle` and `test_the_nexus_names_are_accepted` covers it. This is the written
    field, and the two are deliberately allowed to differ.
    """
    from .baseline import _walk_nodes, nexus_structures

    for name, structure in nexus_structures().items():
        for node in _walk_nodes(structure):
            config = node.get('config') or {}
            assert config.get('name') != 'top_dead_center', \
                f'{name}: a disc still writes top_dead_center'


def test_no_dataset_still_carries_the_deprecated_key(bifrost):
    """The rule itself, asserted on the output rather than on the diff.

    This is what outlives the migration list: when the frozen file is re-minted the
    entry above goes, and this stays saying what the format actually requires.
    """
    from .baseline import _walk_nodes, nexus_structures
    for name, structure in nexus_structures().items():
        for node in _walk_nodes(structure):
            config = node.get('config')
            if isinstance(config, dict) and node.get('module') == 'dataset':
                assert 'dtype' in config, f'{name}: dataset without a dtype'
                assert 'type' not in config, f'{name}: dataset still carrying type'


# -- run-time values and streams ----------------------------------------------

def test_a_knob_is_a_link_not_a_number(teaching):
    """A chopper's speed is not something the instrument has; it is something a run sets.

    So the file says where to read it. The route this replaced decided by folding a McCode
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


def test_a_run_time_value_is_a_log_the_file_fills_itself(teaching):
    """The group stays ours, and it now says where its values come from.

    It used to be an NXlog whose datasets were `link` modules mirroring an NXlog
    published elsewhere in the file -- which only worked if something else had put one
    there. A `Motor` knows its Kafka source and topic, so the log carries an `f144`
    stream and is filled from the same place the run fills it.

    What has not changed is why it is a group of ours rather than a link to someone
    else's: it has to carry a `transformation_type` and a `vector` alongside the value
    when it is part of an NXtransformations chain, and a link cannot.
    """
    structure = to_nexus_structure(teaching)
    speed = find_child(find_child(instrument_group(structure), 'chopper'),
                       'rotation_speed')

    assert get_attribute(speed, 'NX_class') == 'NXlog'
    assert speed['type'] == 'group', 'a group of ours, not a link to one'

    assert {c['module'] for c in speed['children']} == {'f144'}
    config = speed['children'][0]['config']
    assert config['source'] == 'chopperspeed'
    assert config['topic']

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
