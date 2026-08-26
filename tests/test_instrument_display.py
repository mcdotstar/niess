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


def test_a_notebook_gets_a_collapsed_tree(bifrost):
    """`<details>` is the one disclosure widget needing no javascript."""
    html = bifrost._repr_html_()
    assert html.startswith('<details open><summary>')
    # exactly one thing is open: the root, so the header is readable and nothing else
    assert html.count('<details open>') == 1
    assert html.count('<details>') > 100
    assert 'Tank' in html and 'a4' in html


def test_the_notebook_tree_goes_all_the_way_down(bifrost):
    """The point of collapsing is that everything is there to open."""
    html = bifrost._repr_html_()
    # a blade is four levels below the tank: channels -> pairs -> analyzer -> blades
    assert 'blades[0]' in html
    assert 'He3Tube' in html


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
    assert '+ component(s)' in instrument._repr_html_()


def test_a_notebook_gets_the_same_answer(unwalkable):
    instrument = Instrument(name='partial',
                            parts=(Mount(name='secondary', content=unwalkable),))
    assert 'not a niess tree node' in instrument._repr_html_()


# -- the same for the pieces, not just the whole ------------------------------------

def test_a_composite_says_what_it_holds():
    """`Tank` is a Base; the generated repr is a quarter of a million characters."""
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    tank = Tank.from_calibration(tank_parameters())
    text = repr(tank)
    assert text.startswith('Tank: 614 component(s)')
    assert 'channels[0]  Channel  68 component(s)' in text
    assert len(text) < 1000


def test_a_section_gets_the_same_treatment():
    """`Primary` is a Section, which is not a Base -- a user holding one cannot tell."""
    from niess.components.section import Section
    from niess.teaching import Primary
    primary = Primary.from_calibration()
    assert isinstance(primary, Section)
    text = repr(primary)
    assert text.startswith('Primary: 7 component(s)')
    assert 'chopper' in text and 'DiscChopper' in text


def test_a_leaf_says_what_it_is_and_stops():
    """Nothing below it, so nothing to count or to open."""
    from niess.teaching import Primary
    chopper = dict(Primary.from_calibration().__niess_children__())['chopper']
    text = repr(chopper)
    assert text == "DiscChopper 'chopper'"
    assert chopper._repr_html_().count('<details>') == 0


def test_a_long_list_of_children_is_cut_short():
    """Nine channels shows the shape; a hundred would be a scroll, not an answer."""
    from niess.display import TEXT_CHILDREN, text_tree

    class Fake:
        def __init__(self, kids=()):
            self._kids = kids

        def __niess_children__(self):
            return tuple((f'part[{i}]', k) for i, k in enumerate(self._kids))

    wide = Fake([Fake() for _ in range(TEXT_CHILDREN + 5)])
    text = text_tree(wide, header='Fake')
    assert '... 5 more' in text
    assert text.count('part[') == TEXT_CHILDREN


def test_counting_a_subtree_once_is_enough():
    """Rendering asks every node its size; without a cache each subtree is re-counted."""
    from niess.display import leaf_count

    seen = []

    class Counted:
        def __init__(self, kids=()):
            self._kids = kids

        def __niess_children__(self):
            seen.append(self)
            return tuple((f'k[{i}]', k) for i, k in enumerate(self._kids))

    shared = Counted([Counted(), Counted()])
    root = Counted([shared, shared, shared])
    cache = {}
    assert leaf_count(root, cache) == 6
    # the shared subtree is walked once, not once per parent
    assert seen.count(shared) == 1
