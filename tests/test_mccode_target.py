"""McStas emitted from the walk, byte for byte what it was.

This is the gate for the whole refactor. If the instrument the walk produces is
identical to the one `to_mccode` produced, then the walk is a faithful description of
the tree, and every other target can be moved onto it on that basis.
"""
import pytest

from .baseline import (frozen_json, frozen_text, graph_path, instrument_graph,
                       instrument_structure, instrument_text, structure_path)
from .test_baseline import first_difference

from niess.instrument import Instrument, Mount
from niess.mccode import to_mccode


@pytest.fixture(scope='module')
def teaching():
    from niess.teaching import Primary
    return Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration()),
    ))


@pytest.fixture(scope='module')
def bifrost_primary():
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    return Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
    ))


@pytest.fixture(scope='module')
def bifrost():
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    return Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin'),
    ))


@pytest.mark.parametrize('fixture,golden', [
    ('teaching', 'teaching'),
    ('bifrost_primary', 'bifrost_primary'),
    ('bifrost', 'bifrost'),
])
def test_the_walk_emits_the_same_instrument(request, fixture, golden):
    built = instrument_text(to_mccode(request.getfixturevalue(fixture)))
    expected = frozen_text(golden)
    assert built == expected, first_difference(built, expected)


def test_nested_sections_still_become_includes(teaching, bifrost_primary):
    """The text renders them inline, so only the instrument shows they are separate."""
    assert [s.name for s in to_mccode(teaching).included] == ['teaching_guides']
    assert [s.name for s in to_mccode(bifrost_primary).included] == [
        'bifrost_compressor', 'bifrost_curved', 'bifrost_expanding',
        'bifrost_straight', 'bifrost_closing',
    ]


def test_a_flat_section_opens_no_scope(bifrost_primary):
    """Primary carries _flat, so it emits into the instrument rather than into itself."""
    instrument = to_mccode(bifrost_primary)
    assert 'bifrost_primary' not in [s.name for s in instrument.included]
    assert len(instrument.components) == 158


def test_every_scope_is_closed(teaching):
    """A translator that opened an %include and did not close it would be caught."""
    from niess.mccode import McCodeContext
    from niess.walk import walk
    from niess.mccode import MCCODE_REGISTRY
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler

    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    context = McCodeContext(instrument=teaching, assembler=assembler)
    walk(teaching, MCCODE_REGISTRY, context=context)
    assert context.scopes == []
    assert context.assembler is assembler


def test_the_tree_is_unchanged_by_being_emitted(bifrost_primary):
    """Emission reads the tree; it does not write to it."""
    from niess.io.json import to_json
    before = to_json(bifrost_primary.parts[0].content)
    to_mccode(bifrost_primary)
    assert to_json(bifrost_primary.parts[0].content) == before


# -- the tank -----------------------------------------------------------------

def test_the_whole_instrument_matches_structurally(bifrost):
    """What the text cannot show: the %include sections it renders inline.

    Also every WHEN and EXTEND, every parameter and every placement, compared as data
    rather than as 215 kB of text.
    """
    built = to_mccode(bifrost)
    assert instrument_structure(built) == frozen_json(structure_path('bifrost'))


def test_the_emitted_flow_graph_is_unchanged(bifrost):
    assert instrument_graph(to_mccode(bifrost)) == frozen_json(graph_path('bifrost'))


def test_the_tank_emits_what_it_used_to(bifrost):
    built = to_mccode(bifrost)
    names = [c.name for c in built.components]
    assert len(names) == 358
    assert names.index('slits') < names.index('elastic_monitor')
    assert names.index('elastic_monitor') < names.index('channel_1_arm')
    frames = [c for c in built.components
              if c.type.name == 'Arm'
              and c.name.endswith(('_arm', '_analyzer_point', '_detector_angle'))]
    assert len(frames) == 99, 'the coordinate frames, still McStas Arms'


def test_per_particle_state_stays_on_the_mcstas_side(bifrost):
    """secondary_cassette and its WHEN clauses mean nothing to any other target."""
    built = to_mccode(bifrost)
    assert any('secondary_cassette' in block.source for block in built.user)
    assert sum(1 for c in built.components if c.when is not None) == 202
    assert sum(1 for c in built.components if c.extend) == 91


def test_a_multi_opening_disc_still_groups():
    """The GROUP path BIFROST does not exercise: every disc there has one opening.

    A disc whose openings are neither identical nor evenly spaced becomes one McStas
    component per opening, grouped so a neutron passes if it clears any of them.
    """
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
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

    section = Chopped(pack=disc)
    walked = to_mccode(Instrument(name='chopped',
                                  parts=(Mount(name='s', content=section),)))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    section.to_mccode(assembler)

    assert [c.name for c in walked.components] == \
           ['pack_slit_0', 'pack_slit_1', 'pack_slit_2']
    assert {c.group for c in walked.components} == {'pack_group'}
    assert instrument_text(walked) == instrument_text(assembler.instrument)


# -- where the conversion is written ------------------------------------------

def test_a_class_describing_its_own_conversion_needs_no_registration():
    """The ordinary case: write the method on the class and it is found.

    Everything a class contributes to a McStas instrument lives on the class --
    __mccode__ for what it is, to_mccode to contribute to the instrument around it,
    __mccode_enter__/__mccode_exit__ for what a composite needs around its contents.
    """
    from niess.dispatch import ClassHooks
    from niess.mccode import MCCODE_REGISTRY
    from niess.bifrost.channel import Channel
    from niess.bifrost.tank import Tank
    from niess.components.section import Section

    for klass in (Tank, Channel, Section):
        assert hasattr(klass, '__mccode_enter__'), klass.__name__

    from niess.bifrost.parameters import tank_parameters
    tank = Tank.from_calibration(tank_parameters())
    resolved = MCCODE_REGISTRY.resolve_for_object(tank)
    assert isinstance(resolved, ClassHooks)
    assert resolved.obj is tank


def test_a_registered_translator_wins_over_the_class(bifrost_primary):
    """Which is what an instrument-specific conversion needs, and a class you do not own.

    The same reason niess.nexus keeps BIFROST's translators off the shared registry:
    importing a module must not change another instrument's output.
    """
    from niess.mccode import MCCODE_REGISTRY, NiessMcCodeRegistry
    from niess.components.section import Section

    scoped = NiessMcCodeRegistry(parent=MCCODE_REGISTRY)
    entered = []

    class Watch:
        @staticmethod
        def enter(visit):
            entered.append(visit.id)
            return None

        @staticmethod
        def exit(visit, opened):
            pass

    scoped.register(Section)(Watch)
    to_mccode(bifrost_primary, registry=scoped)
    assert entered, 'the registered translator was not used'
    # and the default is untouched
    from niess.dispatch import ClassHooks
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    assert isinstance(
        MCCODE_REGISTRY.resolve_for_object(
            Primary.from_calibration(primary_parameters())),
        ClassHooks)


def test_the_target_module_names_no_component():
    """It is machinery. What each class contributes is written on that class.

    A user asking "what do I need for this to convert to an Instr?" should be able to
    read one class, not hunt through a translator module for the half that lives there.
    """
    from pathlib import Path
    import niess.mccode as module

    source = Path(module.__file__).read_text()
    for name in ('Tank', 'Channel', 'DiscChopper', 'Analyzer', 'Triplet',
                 'Slit_radial_multi', 'secondary_cassette'):
        assert name not in source, f'{name} leaked into the target module'


# -- what the instrument itself declares -------------------------------------------

def test_an_instrument_emits_the_parameters_it_declares():
    """`Instrument.parameters` is knobs stated up front, so they have to reach DEFINE.

    Otherwise the field says nothing: every other parameter in an emitted instrument got
    there as a side effect of whichever component wanted one.
    """
    from mccode_antlr.common import InstrumentParameter
    from niess.instrument import Instrument, Mount
    from niess.mccode import to_mccode
    from niess.teaching import Primary

    a3 = InstrumentParameter.parse('a3/"deg" = 0')
    a4 = InstrumentParameter.parse('a4/"deg" = 0')
    instrument = Instrument(
        name='t', origin='sample_origin', parameters=(a3, a4),
        parts=(Mount(name='primary', content=Primary.from_calibration()),))

    emitted = to_mccode(instrument)
    names = [p.name for p in emitted.parameters]
    assert 'a3' in names and 'a4' in names
    # up front: declared before anything a component asked for on its own account
    assert names[:2] == ['a3', 'a4']
    assert 'a3/"deg"=0' in str(emitted)


def test_declaring_nothing_emits_nothing_extra():
    """The default is an empty tuple, and an instrument that says nothing is unchanged."""
    from niess.instrument import Instrument, Mount
    from niess.mccode import to_mccode
    from niess.teaching import Primary

    plain = Instrument(name='t', origin='sample_origin',
                       parts=(Mount(name='primary', content=Primary.from_calibration()),))
    assert [p.name for p in to_mccode(plain).parameters][0] == 'source_lambda_min'


def test_provenance_can_be_left_out():
    """A file to hand to McStas and nothing else, without the niess bookkeeping."""
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.instrument import Instrument, Mount
    from niess.mccode import to_mccode

    bifrost = Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin')))

    with_it = str(to_mccode(bifrost))
    without = str(to_mccode(bifrost, insert_provenance_metadata=False))

    assert 'niess_provenance' in with_it
    assert 'niess_provenance' not in without
    # every emitter honours it, not only the generic one: the frames an Arm and a
    # Channel declare, and the analyzer and triplet they emit, carry it too
    assert 'reference-frame' not in without
    assert without.count('COMPONENT ') == with_it.count('COMPONENT ')
