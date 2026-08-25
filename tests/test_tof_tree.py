"""tof chopper specs, read off the tree instead of parsed back out of C.

`niess.tof` builds these from what `niess.chopcalc` extracted, which is C *text* --
chopcalc emits text on purpose, so a band recomputes when a speed changes at run time.
tof configures one specific machine and needs numbers, so it parses the text back.
Reading the tree there is no text to parse.
"""
import pytest

from niess.instrument import Instrument, Mount
from niess.tof.tree import chopper_specs


def bifrost_primary():
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    return Primary.from_calibration(primary_parameters())


def as_instrument():
    return Instrument(name='bifrost',
                      parts=(Mount(name='primary', content=bifrost_primary()),))


@pytest.fixture(scope='module')
def existing():
    """What the C-text route produces, for the same instrument."""
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    import niess.tof as tof

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    bifrost_primary().to_mccode(assembler)
    return tof.to_tof_model(assembler)


def test_the_two_routes_describe_the_same_choppers(existing):
    """Same discs, same direction, same phase, same distance -- and the same openings.

    Compared with a tolerance for one reason: the other route writes each window edge
    into C at twelve significant figures and parses it back, so its -19.13 is a rounded
    -19.129999999999995. Reading the disc keeps the number it had. Five parts in a
    thousand million million, in the direction of the tree being right.
    """
    from_tree = chopper_specs(
        as_instrument(), origin=float(existing.source.distance.to(unit='m').value))

    assert len(from_tree) == len(existing.choppers) == 6
    for mine, theirs in zip(from_tree, existing.choppers):
        assert mine.name == theirs.name
        assert mine.frequency == theirs.frequency
        assert mine.anticlockwise == theirs.anticlockwise
        assert mine.phase == pytest.approx(theirs.phase)
        assert mine.distance == pytest.approx(theirs.distance)
        assert mine.open == pytest.approx(theirs.open)
        assert mine.close == pytest.approx(theirs.close)


def test_a_knob_can_be_overridden_by_name(existing):
    """Running the same instrument at a different speed.

    The disc names the knob it declared, so nothing here repeats the convention -- which
    the other route has to, having only a parameter name parsed out of a component call.
    """
    slowed = chopper_specs(as_instrument(),
                           values={'pulse_shaping_chopper_1speed': 7.0}, origin=0.05)
    assert slowed[0].name == 'pulse_shaping_chopper_1'
    assert slowed[0].frequency == 7.0
    # and nothing else moved
    assert [s.frequency for s in slowed[1:]] == [14.0] * 5


def test_the_origin_belongs_to_the_model_not_the_instrument():
    """An ESS source in tof carries a 0.05 m facility offset; the moderator is at zero.

    So it is an argument rather than something read off the tree, and getting it from
    anywhere else silently shifts every chopper.
    """
    at_zero = chopper_specs(as_instrument(), origin=0.0)
    offset = chopper_specs(as_instrument(), origin=0.05)
    assert offset[0].distance == pytest.approx(at_zero[0].distance + 0.05)


def test_specs_come_out_in_beam_order():
    specs = chopper_specs(as_instrument(), origin=0.05)
    assert [s.distance for s in specs] == sorted(s.distance for s in specs)
