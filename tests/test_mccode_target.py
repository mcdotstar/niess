"""McStas emitted from the walk, byte for byte what it was.

This is the gate for the whole refactor. If the instrument the walk produces is
identical to the one `to_mccode` produced, then the walk is a faithful description of
the tree, and every other target can be moved onto it on that basis.
"""
import pytest

from .baseline import frozen_text, instrument_text
from .test_baseline import first_difference

from niess.instrument import Instrument, Mount
from niess.targets.mccode import to_mccode


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


@pytest.mark.parametrize('fixture,golden', [
    ('teaching', 'teaching'),
    ('bifrost_primary', 'bifrost_primary'),
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
    from niess.targets.mccode import McCodeContext
    from niess.walk import walk
    from niess.targets.mccode import MCCODE_REGISTRY
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
