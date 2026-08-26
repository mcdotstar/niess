"""What an instrument looks like when you type its name.

msgspec generates a repr from the fields, and an instrument's fields are the whole tree:
BIFROST comes out at nearly 300 000 characters of nested scipp variables. Displaying one
by accident floods the terminal and says nothing, so both `Instrument` and `Mount` say
what they are and how big instead.
"""
import pytest

from mccode_antlr.common import InstrumentParameter
from niess.instrument import Instrument, Mount


@pytest.fixture(scope='module')
def teaching():
    from niess.teaching import Primary
    return Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration()),
    ))


@pytest.fixture(scope='module')
def bifrost():
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    a4 = InstrumentParameter.parse('a4/"degree" = 0')
    return Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin', rotation=(0, a4, 0)),
    ))


def test_it_says_what_the_instrument_is(teaching):
    text = repr(teaching)
    assert text.startswith('teaching: 1 part(s), 7 component(s)')
    assert "origin 'sample_origin'" in text
    assert 'primary' in text and 'Primary' in text


def test_it_is_short_enough_to_read(bifrost):
    """The whole point. The generated repr is ~300 000 characters."""
    text = repr(bifrost)
    assert len(text) < 1000
    assert text.count('\n') < 10


def test_it_counts_the_components_of_each_part(bifrost):
    """Leaves, not nodes -- the number meant by "how big is this?"."""
    from niess.tree import leaves
    counts = {label: count for label, _, count in bifrost.summary()}
    assert set(counts) == {'primary', 'tank'}
    for mount in bifrost.parts:
        assert counts[mount.name] == len(leaves(mount.content))
    assert sum(counts.values()) == len(leaves(bifrost))


def test_it_says_where_a_part_hangs_and_how_it_turns(bifrost):
    text = repr(bifrost)
    assert 'sample_origin' in text
    # the angle is a run-time knob, so it appears by name rather than as a number
    assert 'turned (0, a4, 0)' in text
    assert 'run-time parameters: a4' in text


def test_a_part_that_hangs_from_nothing_says_nothing(teaching):
    assert '←' not in repr(teaching)
    assert 'turned' not in repr(teaching)


def test_a_notebook_gets_a_table(bifrost):
    markdown = bifrost._repr_markdown_()
    assert markdown.startswith('**bifrost**')
    assert '| part | is a | components | mounted |' in markdown
    assert '| `tank` | `Tank` |' in markdown
    assert '`a4`' in markdown


def test_a_mount_does_not_print_what_it_holds(bifrost):
    """`instrument.parts` would otherwise flood just as badly."""
    text = repr(bifrost.parts[1])
    assert text == 'Mount tank: Tank ← sample_origin turned (0, a4, 0)'
    assert repr(bifrost.parts[0]) == 'Mount primary: Primary'


def test_displaying_an_instrument_does_not_walk_it_twice(bifrost):
    """A repr is typed by reflex, so it has to stay cheap."""
    import time
    start = time.perf_counter()
    repr(bifrost)
    assert time.perf_counter() - start < 2.0


# -- a part that is not a tree node ------------------------------------------------

@pytest.fixture(scope='module')
def unwalkable():
    """`IndirectSecondary` derives from `object`: no `__niess_children__`, so no walk.

    `niess.bifrost.BIFROST` holds one, which is how this turns up in practice.
    """
    from niess.bifrost import BIFROST
    from niess.bifrost.parameters import tank_parameters
    return BIFROST.from_calibration(**tank_parameters()).secondary


def test_a_part_that_cannot_be_walked_is_reported_not_raised(unwalkable):
    """A repr that raises takes away the first thing anyone does with a broken object."""
    instrument = Instrument(name='partial',
                            parts=(Mount(name='secondary', content=unwalkable),))
    text = repr(instrument)
    assert 'not a niess tree node' in text
    assert 'IndirectSecondary' in text
    assert instrument.summary() == (('secondary', 'IndirectSecondary', None),)


def test_the_total_says_it_is_incomplete(unwalkable):
    """`158+` rather than `158`: one part was not counted, and the count should say so."""
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    instrument = Instrument(name='partial', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='secondary', content=unwalkable),
    ))
    assert '+ component(s)' in repr(instrument)
    assert '+ component(s)' in instrument._repr_markdown_()


def test_a_notebook_gets_the_same_answer(unwalkable):
    instrument = Instrument(name='partial',
                            parts=(Mount(name='secondary', content=unwalkable),))
    assert '**not a niess tree node**' in instrument._repr_markdown_()
