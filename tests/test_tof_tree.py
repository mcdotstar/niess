"""tof chopper specs, read off the tree instead of parsed back out of C.

`niess.tof` builds these from what `niess.chopcalc` extracted, which is C *text* --
chopcalc emits text on purpose, so a band recomputes when a speed changes at run time.
tof configures one specific machine and needs numbers, so it parses the text back.
Reading the tree there is no text to parse.
"""
import pytest
import scipp as sc

from niess.instrument import Instrument, Mount
from niess.tof import chopper_specs


def bifrost_primary():
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    return Primary.from_calibration(primary_parameters())


def as_instrument():
    return Instrument(name='bifrost',
                      parts=(Mount(name='primary', content=bifrost_primary()),))






def test_the_choppers_of_bifrost_are_what_they_are():
    """What the two routes used to be compared against each other for.

    The instrument-reading route is gone, so there is nothing to compare with -- these
    are the values that comparison agreed on, written down. Six discs, in beam order,
    each with the direction, phase and openings the calibration gives it.
    """
    specs = chopper_specs(as_instrument(), origin=0.05)

    assert [(s.name, round(s.distance, 4)) for s in specs] == [
        ('pulse_shaping_chopper_1', 6.3749),
        ('pulse_shaping_chopper_2', 6.4239),
        ('frame_overlap_chopper_1', 8.5716),
        ('frame_overlap_chopper_2', 15.0207),
        ('bandwidth_chopper_1', 78.0309),
        ('bandwidth_chopper_2', 78.0659),
    ]
    assert all(s.frequency == 14.0 for s in specs)
    assert all(s.anticlockwise for s in specs)
    assert all(len(s.open) == len(s.close) == 1 for s in specs)
    # every disc is at its calibrated delay, so nothing is phased away from the mark
    assert all(s.phase == 0.0 for s in specs)


def test_a_knob_can_be_overridden_by_name():
    """Running the same instrument at a different speed.

    The disc names the knob it declared, so nothing here repeats the convention.
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
    from niess.tof import to_tof_model
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
    from niess.tof import to_tof_model
    setup = to_tof_model(teaching_tree(), neutrons=1000,
                         values={'source_lambda_min': sc.scalar(0.2, unit='nm')})
    used = {use.name: use for use in setup.parameters}
    assert used['source_lambda_min'].value == pytest.approx(2.0)
    assert used['source_lambda_min'].unit == 'angstrom'
    assert used['source_lambda_min'].overridden
    assert not used['source_lambda_max'].overridden


def test_a_source_may_be_supplied_so_the_model_can_be_built_offline():
    """Building one fetches the facility's pulse profile; this is how to not."""
    import numpy as np
    tof = pytest.importorskip('tof')
    from niess.tof import to_tof_model

    given = tof.Source.from_neutrons(
        birth_times=sc.array(dims=['event'], values=np.linspace(0, 2.86e-3, 50), unit='s'),
        wavelengths=sc.array(dims=['event'], values=np.linspace(0.5, 10.0, 50),
                             unit='angstrom'),
        distance=sc.scalar(0.0, unit='m'))
    setup = to_tof_model(teaching_tree(), source=given)
    assert setup.source is given
    # a source handed over already carries its own band, so none was read off the
    # instrument and none is reported as used
    assert not [use for use in setup.parameters if 'lambda' in use.name]


def test_the_supplied_source_survives_with_values():
    """Rebuilding for a different chopper speed must not go and fetch a profile."""
    import numpy as np
    tof = pytest.importorskip('tof')
    from niess.tof import to_tof_model

    given = tof.Source.from_neutrons(
        birth_times=sc.array(dims=['event'], values=np.linspace(0, 2.86e-3, 50), unit='s'),
        wavelengths=sc.array(dims=['event'], values=np.linspace(0.5, 10.0, 50),
                             unit='angstrom'),
        distance=sc.scalar(0.0, unit='m'))
    setup = to_tof_model(teaching_tree(), source=given)
    assert setup.with_values(chopperspeed=70.0).source is given


def test_the_last_detector_can_be_named():
    tof = pytest.importorskip('tof')
    from niess.tof import to_tof_model
    setup = to_tof_model(teaching_tree(), neutrons=1000, sample='monitor')
    assert 'monitor' in setup.detectors
