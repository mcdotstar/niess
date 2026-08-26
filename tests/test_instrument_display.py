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
    assert html.startswith('<style>')          # the column widths this tree used
    assert '<div class="niess-tree">' in html
    assert '<details open><summary>' in html
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

    A real niess object rather than a stub, because the point is that this happens: a
    tank converted for event processing is not a tree, and neither is `None`, and
    neither is a stray dict from a mis-decorated factory.
    """
    import scipp as sc
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    tank = Tank.from_calibration(tank_parameters())
    return tank.to_secondary(sample=sc.vector([0, 0, 0.], unit='m'))


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
    assert 'channels[0]  Channel' in text
    assert '68 component(s)' in text
    assert len(text) < 1200


def test_a_section_gets_the_same_treatment():
    """`Primary` is a Section, which is not a Base -- a user holding one cannot tell."""
    from niess.components.section import Section
    from niess.teaching import Primary
    primary = Primary.from_calibration()
    assert isinstance(primary, Section)
    text = repr(primary)
    assert text.startswith('Primary: 7 component(s)')
    assert 'chopper' in text and 'DiscChopper' in text


def test_a_leaf_says_what_it_is_and_what_it_is_set_to():
    """Nothing below it to count or to open, so its fields are the whole answer."""
    from niess.teaching import Primary
    chopper = dict(Primary.from_calibration().__niess_children__())['chopper']
    text = repr(chopper)
    assert text.startswith("DiscChopper 'chopper'")
    assert 'radius=0.35 m' in text
    assert 'velocity=14 Hz' in text
    # nothing below it, so nothing to open
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
    assert '… 5 more' in text
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


# -- alignment and parameters ------------------------------------------------------

def test_classes_line_up_under_each_other():
    """Each sibling group is its own column, sized to its own widest label."""
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters

    lines = repr(Tank.from_calibration(tank_parameters())).splitlines()[1:]
    columns = {line.index(line.strip().split()[1]) for line in lines}
    assert len(columns) == 1, 'the class column is ragged'


def test_a_group_is_not_padded_to_some_other_groups_width():
    """A short list is not indented to make room for a wide label somewhere else."""
    from niess.display import text_tree

    class Fake:
        def __init__(self, kids=()):
            self._kids = kids

        def __niess_children__(self):
            return self._kids

    narrow = Fake((('a', Fake()), ('b', Fake())))
    text = text_tree(narrow, header='Fake')
    # two characters of indent, the label, two of gap -- nothing wider intrudes
    assert text.splitlines()[1] == '  a  Fake'


def test_a_small_thing_shows_its_parameters_and_a_big_one_does_not():
    """The judgement the flag exists to override: BIFROST lists parts, a chopper lists
    what it is set to."""
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    from niess.teaching import Primary

    chopper = dict(Primary.from_calibration().__niess_children__())['chopper']
    assert 'radius=' in repr(chopper)
    assert 'radius=' not in repr(Tank.from_calibration(tank_parameters()))


def test_the_flag_overrides_the_judgement_either_way():
    from niess.display import show
    from niess.teaching import Primary

    primary = Primary.from_calibration()
    assert 'radius=' in show(primary)                      # 7 components, so shown
    assert 'radius=' not in show(primary, parameters=False)

    chopper = dict(primary.__niess_children__())['chopper']
    assert 'radius=' not in show(chopper, parameters=False)


def test_the_module_flag_applies_to_repr_which_takes_no_arguments():
    import niess.display as display
    from niess.teaching import Primary

    primary = Primary.from_calibration()
    held = display.PARAMETERS
    try:
        display.PARAMETERS = False
        assert 'radius=' not in repr(primary)
        display.PARAMETERS = True
        assert 'radius=' in repr(primary)
    finally:
        display.PARAMETERS = held


def test_a_parameter_is_short_or_it_is_not_worth_showing():
    """A scipp variable's own repr is three lines of table; these are one column."""
    from niess.display import value_text
    import scipp as sc
    from scipp.spatial import rotations_from_rotvecs

    assert value_text(sc.scalar(0.35, unit='m')) == '0.35 m'
    assert value_text(sc.scalar(2.0)) == '2'                     # dimensionless
    assert value_text(sc.vector([0, 0, 6.76], unit='m')) == '(0, 0, 6.76) m'
    assert value_text(sc.array(dims=['edges'], values=[1., 2.], unit='deg')) == '[2] deg'
    # an identity rotation is the default and says nothing
    assert value_text(rotations_from_rotvecs(sc.vector([0, 0, 0.], unit='deg'))) is None
    assert value_text(rotations_from_rotvecs(
        sc.vector([0, 0, 90.], unit='deg'))) == 'rotated'
    assert value_text(None) is None


def test_children_are_not_listed_as_parameters():
    """`channels=[9]` would restate the tree directly underneath it."""
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    from niess.display import show

    text = show(Tank.from_calibration(tank_parameters()), parameters=True)
    assert 'channels=' not in text
    assert 'pairs=' not in text


def test_a_row_inside_a_tree_is_clipped_but_the_header_is_not():
    """The node asked for gets its whole answer; the ones listed under it get a line."""
    from niess.display import PARAMETER_WIDTH
    from niess.teaching import Primary

    primary = Primary.from_calibration()
    rows = repr(primary).splitlines()[1:]
    assert any(row.endswith('…') for row in rows)
    assert all(len(row) < 200 for row in rows)

    chopper = dict(primary.__niess_children__())['chopper']
    header = repr(chopper).splitlines()[0]
    assert not header.endswith('…')
    assert len(header) > PARAMETER_WIDTH


def test_the_column_css_is_written_once_not_on_every_row():
    """A thousand rows of `style="display:inline-block;min-width:12ch"` was two thirds
    of the output."""
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters

    html = Tank.from_calibration(tank_parameters())._repr_html_()
    assert html.count('<style>') == 1
    assert 'display:inline-block' not in html[html.index('</style>'):]
    # class names are prefixed: a <style> in notebook output is not scoped to its cell
    assert '.niess-tree .niess-c' in html
