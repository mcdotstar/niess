"""NeXus built from the tree instead of from an emitted McStas instrument.

`niess.nexus` converts an assembled instrument and recovers everything it needs from it:
placement from resolve_orientations, run-time values by folding DECLARE blocks, a
detector's arc and triplet by matching a regex against a generated WHEN clause. This
reads the tree, where all of that is simply present.
"""
import pytest

from niess.instrument import Instrument, Mount
from niess.nexus.nodes import find_child, get_attribute, node_name
from niess.targets.nexus import to_nexus_structure


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
    from niess.nexus import to_nexus_structure as from_instrument
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
    spaced, so it becomes one component per opening. `niess.nexus` reassembles it from
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
    from niess.nexus import to_nexus_structure as from_instrument

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
    from niess.targets.nexus import NiessNexusRegistry

    class Odd:
        def __nexus_leaf__(self, visit):
            return None

    resolved = NiessNexusRegistry().resolve_for_object(Odd())
    assert isinstance(resolved, ClassHooks)


def test_registering_wins_over_the_class():
    from niess.targets.nexus import NEXUS_REGISTRY, NiessNexusRegistry
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
    from niess.targets.nexus import BIFROST_REGISTRY
    counted = classes(to_nexus_structure(bifrost, registry=BIFROST_REGISTRY))
    assert counted['NXcrystal'] == 45      # one per arm, not one per blade
    assert counted['NXdetector'] == 45     # one per arm, not one per tube
    assert counted['NXguide'] == 119
    assert counted['NXdisk_chopper'] == 6
    assert sum(counted.values()) == 357


def test_reading_the_tree_classifies_more_than_reading_the_instrument(bifrost):
    """The windows and collimators are recognisable here and were not before.

    A Filter with nothing to say emits as a McStas Arm, so an instrument-reading
    converter sees an Arm and files it under NXcoordinate_system. The tree says Filter.
    """
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.nexus import to_nexus_structure as from_instrument
    from niess.nexus.bifrost import BIFROST_REGISTRY as INSTRUMENT_REGISTRY
    from niess.targets.nexus import BIFROST_REGISTRY
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
    from niess.targets.nexus import BIFROST_REGISTRY, icd_pixel

    structure = to_nexus_structure(bifrost, registry=BIFROST_REGISTRY)
    detector = find_child(instrument_group(structure), 'channel_3_2_triplet')
    numbers = value(detector, 'detector_number')
    # channel 3 is cassette index 2, arm 2 is arc index 1
    resolution = len(numbers[0])
    assert numbers[0][0] == icd_pixel(resolution, 1, 2, 0, 0)


def test_the_radial_slit_bank_is_the_one_thing_missing(bifrost):
    """It is emitted by Tank's McStas hook and has no object of its own yet.

    Which is the remaining piece of "the McStas-only artefacts become real objects":
    the slits are a physical aperture, and no target but McStas can currently see them.
    """
    from niess.targets.nexus import BIFROST_REGISTRY

    structure = to_nexus_structure(bifrost, registry=BIFROST_REGISTRY)
    assert find_child(instrument_group(structure), 'slits') is None


def test_the_frozen_structure_is_unchanged(bifrost):
    from .baseline import NEXUS_STRUCTURES, frozen_json, nexus_structures
    assert nexus_structures() == frozen_json(NEXUS_STRUCTURES)
