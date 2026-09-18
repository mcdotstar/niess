"""tof chopper specs, read off the tree instead of parsed back out of C.

`niess.tof` builds these from what `niess.chopcalc` extracted, which is C *text* --
chopcalc emits text on purpose, so a band recomputes when a speed changes at run time.
tof configures one specific machine and needs numbers, so it parses the text back.
Reading the tree there is no text to parse.
"""
import pytest
import scipp as sc

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
    """What the C-text route produces, for the same instrument.

    `niess.tof` imports without the scipp `tof` package and reaches it only when a model
    is actually built -- which is here, inside a fixture, rather than at the top of this
    module. So `importorskip` has to be here too: without it the ImportError surfaces as
    a fixture *error* in every test that asks for `existing`, and a checkout with no
    extras does not run the suite green, which `tests/optional_dependencies.py` says it
    must.
    """
    pytest.importorskip('tof', reason="the C-text comparison builds a tof.Model")

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


# -- values arrive with their own units -------------------------------------------

def teaching_tree():
    from niess.teaching import Primary
    return Instrument(name='teaching', origin='sample_origin',
                      parts=(Mount(name='primary', content=Primary.from_calibration()),))


@pytest.mark.parametrize('given,expected', [
    (7.0, 7.0),
    (sc.scalar(7.0, unit='Hz'), 7.0),
    (sc.scalar(0.007, unit='kHz'), 7.0),
])
def test_a_speed_is_converted_to_the_unit_the_disc_declares(given, expected):
    """A calculator is entitled to hand back kHz; the disc declares its knob in Hz.

    The instrument-reading route takes the unit from the DEFINE line. Reading the tree
    there is no DEFINE line yet -- the disc is what writes it -- so the unit comes from
    the disc, and the two agree by construction rather than by coincidence.
    """
    specs = chopper_specs(as_instrument(),
                          values={'pulse_shaping_chopper_1speed': given}, origin=0.05)
    assert specs[0].frequency == pytest.approx(expected)


def test_a_delay_in_milliseconds_is_converted_to_seconds():
    from niess.tof.mapping import delay_to_phase
    specs = chopper_specs(as_instrument(),
                          values={'pulse_shaping_chopper_1delay': sc.scalar(3.0, unit='ms')},
                          origin=0.05)
    assert specs[0].phase == pytest.approx(delay_to_phase(0.003, 14.0))


def test_a_value_in_the_wrong_unit_is_refused_by_name():
    with pytest.raises(ValueError, match="pulse_shaping_chopper_1speed is declared in 'Hz'"):
        chopper_specs(as_instrument(),
                      values={'pulse_shaping_chopper_1speed': sc.scalar(1.0, unit='m')},
                      origin=0.05)


def test_overriding_something_that_is_not_a_knob_is_refused():
    """A misspelled knob would otherwise change nothing and say nothing."""
    with pytest.raises(ValueError, match='are not knobs of'):
        chopper_specs(as_instrument(), values={'not_a_knob': 1.0}, origin=0.05)


# -- and the same through the whole model ----------------------------------------

def test_the_whole_model_takes_values_with_units():
    pytest.importorskip('tof')
    from niess.tof.tree import to_tof_model
    setup = to_tof_model(teaching_tree(), neutrons=1000).with_values(
        chopperspeed=sc.scalar(0.07, unit='kHz'),
        chopperdelay=sc.scalar(17.0, unit='ms'))
    used = {use.name: use for use in setup.parameters}
    assert setup.choppers[0].frequency == pytest.approx(70.0)
    assert used['chopperspeed'].value == pytest.approx(70.0)
    assert used['chopperdelay'].value == pytest.approx(0.017)
    assert used['chopperdelay'].unit == 's'
    assert all(used[name].overridden for name in ('chopperspeed', 'chopperdelay'))


def test_a_wavelength_bound_is_converted_to_what_its_own_parameter_declares():
    """The band is angstrom to `tof`, whatever the caller measured it in."""
    pytest.importorskip('tof')
    from niess.tof.tree import to_tof_model
    setup = to_tof_model(teaching_tree(), neutrons=1000,
                         values={'source_lambda_min': sc.scalar(0.2, unit='nm')})
    used = {use.name: use for use in setup.parameters}
    assert used['source_lambda_min'].value == pytest.approx(2.0)
    assert used['source_lambda_min'].unit == 'angstrom'
    assert used['source_lambda_min'].overridden
    assert not used['source_lambda_max'].overridden
