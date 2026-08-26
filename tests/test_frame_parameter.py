"""A frame turned by a knob a run sets, rather than by an angle the instrument has.

BIFROST's tank turns by a4 and its sample by a3, and neither is known when the
instrument is described. A `Frame` says so by carrying the `InstrumentParameter` in the
axis slot it turns about, and each target renders it as the knob it is: McStas names it
in `ROTATED`, NeXus links the transformation to its `NXlog`, and CAD -- which has to
draw something -- uses the value it is declared with.
"""
import pytest
import scipp as sc
from mccode_antlr.common import InstrumentParameter

from niess.components.frame import Frame
from niess.instrument import Instrument, Mount


@pytest.fixture
def a4():
    return InstrumentParameter.parse('a4/"deg" = 45')


@pytest.fixture
def turned(a4):
    return Instrument(name='t', parameters=(a4,), parts=(
        Mount(name='turntable', content=Frame(name='turntable', rotation=(0, a4, 0))),))


def test_a_knob_stays_a_knob(a4):
    frame = Frame(name='f', rotation=(0, a4, 0))
    assert frame.angles()[1] is a4
    assert frame.mccode_angles() == (0, 'a4', 0)
    assert [p.name for p in frame.parameters()] == ['a4']


def test_a_declared_rotation_vector_is_unchanged():
    """The other spelling still means what it meant; 40 degrees emits as 40."""
    frame = Frame(name='f',
                  rotation=sc.vector([0., 1., 0.]) * sc.scalar(40.0, unit='degree'))
    assert frame.angles() == (0.0, 40.0, 0.0)
    assert frame.parameters() == ()
    assert frame.declared_angles() is None


def test_mcstas_names_the_knob_in_rotated(turned):
    from niess.mccode import to_mccode
    text = str(to_mccode(turned))
    assert 'ROTATED (0, a4, 0)' in text
    # naming it is not enough: it has to be a parameter of the instrument
    assert 'a4/"deg"=45' in text


def test_nexus_links_the_transformation_to_the_knobs_log(turned):
    """A turn a run sets is not a number the file can state, but where to read it."""
    from niess.nexus import to_nexus_structure
    from niess.nexus.nodes import children_of, find_child, get_attribute

    def descend(node):
        for child in children_of(node):
            yield child
            yield from descend(child)

    structure = to_nexus_structure(turned)
    rotation = next(n for n in descend(structure) if n.get('name') == 'rotation_y')
    assert get_attribute(rotation, 'NX_class') == 'NXlog'
    assert get_attribute(rotation, 'transformation_type') == 'rotation'
    assert get_attribute(rotation, 'vector') == [0.0, 1.0, 0.0]
    value = find_child(rotation, 'value')
    assert value['config']['source'] == '/entry/parameters/a4/value'


def test_a_drawing_uses_the_value_the_knob_is_declared_with(a4):
    """CAD has to put the thing somewhere, and a run that sets nothing gets this."""
    from niess.spatial import mccode_ordered_angles
    frame = Frame(name='f', rotation=(0, a4, 0))
    assert mccode_ordered_angles(frame.orientation()) == pytest.approx((0.0, 45.0, 0.0))


def test_a_knob_that_is_not_turning_still_declares_itself(turned):
    """Its default is what a run gets by default, not a reason to leave it out."""
    from niess.mccode import to_mccode
    zero = InstrumentParameter.parse('a3/"deg" = 0')
    instrument = Instrument(name='t', parameters=(zero,), parts=(
        Mount(name='t', content=Frame(name='t', rotation=(0, zero, 0))),))
    text = str(to_mccode(instrument))
    assert 'ROTATED (0, a3, 0)' in text


def test_several_axes_compose_in_mccode_order(a4):
    """Extrinsic x then y then z, which is what ROTATED means."""
    from niess.spatial import mccode_ordered_angles
    frame = Frame(name='f', rotation=(30.0, 40.0, 0.0))
    assert mccode_ordered_angles(frame.orientation()) == pytest.approx((30.0, 40.0, 0.0))
