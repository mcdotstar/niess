"""Setting up a `tof.Model` from an instrument niess emitted.

The load-bearing test here is the first one. `tof` describes a chopper by an angle, a
non-negative frequency, a separate direction and a phase *angle*; niess describes one by a
signed speed and a delay in *seconds*. Converting between them is exactly the shape of
several bugs this codebase has had, so the conversion is pinned by comparing when `tof`
says the disc is open against when niess says it is -- not by asserting the expressions.
"""
import numpy as np
import pytest

tof = pytest.importorskip('tof')

import scipp as sc
from mccode_antlr import Flavor
from mccode_antlr.assembler import Assembler
from scipp.spatial import rotations_from_rotvecs

from niess.tof import delay_to_phase, spec_from_windows
from niess.tof.via_instr import to_tof_model

# Three openings, 20/40/20 degrees wide, centred 20/120/360 from the mark. Asymmetric on
# purpose: mirrored about the beam these land nowhere near themselves, so a direction or
# angle-sign error cannot pass unnoticed.
EDGES = [10.0, 30.0, 100.0, 140.0, 350.0, 370.0]
BEAM = 90.0
DELAY = 0.017


def disc(speed, *, edges=None, beam=BEAM, delay=DELAY, name='pack'):
    """A niess disc chopper, emitted into an instrument, as a calibration would build it."""
    from niess.components import DiscChopper
    return DiscChopper.from_calibration({
        'name': name,
        'position': sc.vector([0, 0, 6.0], unit='m'),
        'orientation': rotations_from_rotvecs(sc.vector([0, 0, 0.0], unit='deg')),
        'radius': sc.scalar(0.35, unit='m'),
        'height': sc.scalar(0.06, unit='m'),
        'frequency': sc.scalar(speed, unit='Hz'),
        'delay': sc.scalar(delay, unit='s'),
        'beam_angle': sc.scalar(beam, unit='deg'),
        'windows': sc.array(values=EDGES if edges is None else edges,
                            dims=['edges'], unit='deg'),
    })


def offline_source(distance=0.0):
    """A source that needs no pulse profile, so the suite never reaches the network."""
    rng = np.random.default_rng(1)
    return tof.Source.from_neutrons(
        birth_times=sc.array(dims=['event'], values=rng.uniform(0, 2.86e-3, 500),
                             unit='s'),
        wavelengths=sc.array(dims=['event'], values=rng.uniform(0.5, 10.0, 500),
                             unit='angstrom'),
        distance=sc.scalar(distance, unit='m'),
    )


def built(speed, **kwargs):
    """The `TofSetup` for an instrument holding one disc."""
    assembler = Assembler('bare', flavor=Flavor.MCSTAS)
    assembler.parameter('source_lambda_min/"angstrom"=0.75')
    assembler.parameter('source_lambda_max/"angstrom"=10.0')
    assembler.component('source', 'ESS_butterfly', at=((0, 0, 0), 'ABSOLUTE'),
                        parameters={'Lmin': 'source_lambda_min',
                                    'Lmax': 'source_lambda_max'})
    disc(speed, **kwargs).to_mccode(assembler, at='source', rotate='source')
    return to_tof_model(assembler, source=offline_source())


def wrapped(delta, period):
    """`delta` reduced to (-period/2, period/2].

    Not `% period`: two times that agree can straddle the wrap and come out as 0 and
    period - eps, which would make the comparison flaky rather than decisive.
    """
    return delta - period * np.round(delta / period)


def niess_edge_time(edge, speed, *, beam=BEAM, delay=DELAY):
    """When the disc point `edge` degrees from the mark is on the beam.

    niess' own rule, stated in `DiscChopper`: an edge at angle `a` from the point the
    delay refers to is on the beam at `delay + a / (360 * speed)`, with `a = beam - edge`
    and the speed signed.
    """
    return delay + (beam - edge) / (360.0 * speed)


# -- the conversion --------------------------------------------------------------

@pytest.mark.parametrize('speed', [14.0, -14.0])
def test_the_cutouts_open_when_the_niess_disc_opens(speed):
    """Both directions, a non-zero delay, and an asymmetric disc.

    Every plausible way of getting this wrong -- negating the phase, swapping the
    direction, mirroring the angles -- moves at least one opening, and this checks all
    three of them against niess' own rule rather than against a remembered expression.
    """
    setup = built(speed)
    assert len(setup.choppers) == 1
    chopper = setup.model.choppers['pack']
    period = 1.0 / abs(speed)

    assert chopper.frequency.value == pytest.approx(abs(speed))
    assert chopper.direction is (tof.AntiClockwise if speed > 0 else tof.Clockwise)
    assert len(chopper.open) == len(EDGES) // 2

    opened, closed = chopper.open_close_times(
        time_limit=sc.scalar(3 * period, unit='s'), unit='s')
    got = list(zip(opened.values, closed.values))

    wants = []
    for low, high in zip(EDGES[::2], EDGES[1::2]):
        a, b = niess_edge_time(low, speed), niess_edge_time(high, speed)
        wants.append((min(a, b), max(a, b)))

    # every opening the disc has, tof has, at the same instant modulo one turn
    for want_open, want_close in wants:
        matches = [(o, c) for o, c in got if abs(wrapped(o - want_open, period)) < 1e-12]
        assert matches, f'no cutout opens at {want_open}'
        for _, close in matches:
            assert wrapped(close - want_close, period) == pytest.approx(0.0, abs=1e-12)

    # ...and none it does not: a mirror error would add three phantom cutouts
    for open_at, _ in got:
        assert any(abs(wrapped(open_at - w, period)) < 1e-12 for w, _ in wants)


def test_reversing_the_disc_is_not_the_same_chopper():
    """Or the test above could pass by symmetry rather than by being right."""
    period = 1.0 / 14.0
    forward = [niess_edge_time(e, 14.0) for e in EDGES]
    reverse = [niess_edge_time(e, -14.0) for e in EDGES]
    assert all(abs(wrapped(f - r, period)) > 1e-6 for f, r in zip(forward, reverse))


def test_the_phase_does_not_flip_with_the_direction():
    """A delay is a time, and a later time is later whichever way the disc turns.

    A NeXus phase is an angle in the disc's rotating frame and *does* flip -- which is why
    `tof.Chopper.from_nexus` negates it for a negative speed. Conflating the two is the
    single most inviting mistake here.
    """
    assert delay_to_phase(DELAY, 14.0) == pytest.approx(delay_to_phase(DELAY, -14.0))
    assert delay_to_phase(DELAY, 14.0) == pytest.approx(360.0 * 14.0 * DELAY)


def test_a_stationary_disc_is_refused():
    with pytest.raises(ValueError, match='not turning'):
        spec_from_windows(name='x', windows=[(0.0, 1.0)], delay=0.0, speed=0.0,
                          distance=1.0)


def test_a_split_disc_becomes_one_chopper_with_several_cutouts():
    """niess emits a multi-opening disc as one GROUPed DiskChopper per opening.

    `tof` has no notion of a group -- one disc is one chopper with several cutouts -- so
    the openings have to be put back together, and the components they were split across
    must not each become a chopper of their own.
    """
    assembler = Assembler('bare', flavor=Flavor.MCSTAS)
    assembler.parameter('source_lambda_min/"angstrom"=0.75')
    assembler.parameter('source_lambda_max/"angstrom"=10.0')
    assembler.component('source', 'ESS_butterfly', at=((0, 0, 0), 'ABSOLUTE'),
                        parameters={'Lmin': 'source_lambda_min',
                                    'Lmax': 'source_lambda_max'})
    disc(14.0).to_mccode(assembler, at='source', rotate='source')

    emitted = [c.name for c in assembler.instrument.components
               if c.type.name == 'DiskChopper']
    assert emitted == ['pack_slit_0', 'pack_slit_1', 'pack_slit_2']

    setup = to_tof_model(assembler, source=offline_source())
    assert list(setup.model.choppers) == ['pack']
    assert len(setup.model.choppers['pack'].open) == 3


# -- what comes out of an instrument ---------------------------------------------

def teaching_setup(**kwargs):
    from niess.teaching import Primary
    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    Primary.from_calibration().to_mccode(assembler)
    return to_tof_model(assembler, source=offline_source(), **kwargs)


def test_monitors_and_the_sample_become_detectors():
    setup = teaching_setup()
    assert setup.detectors == ('monitor', 'sample_origin')
    assert [c.name for c in setup.choppers] == ['chopper']


def test_distances_are_measured_along_the_beam_from_the_source():
    """`tof` measures from the same zero as its source, so the source's own distance is
    part of every component's."""
    setup = teaching_setup()
    assert setup.choppers[0].distance == pytest.approx(6.76, abs=1e-9)
    assert setup.model.detectors['sample_origin'].distance.value == pytest.approx(8.46,
                                                                                  abs=1e-9)


def test_a_source_with_a_distance_offsets_everything():
    from niess.teaching import Primary
    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    Primary.from_calibration().to_mccode(assembler)
    setup = to_tof_model(assembler, source=offline_source(distance=2.5))
    assert setup.choppers[0].distance == pytest.approx(2.5 + 6.76, abs=1e-9)


def test_the_model_is_ready_to_run():
    """The whole point of returning a Model rather than a description of one."""
    setup = teaching_setup()
    result = setup.model.run()
    for name in setup.detectors:
        assert len(result.detectors[name].toa.data.flatten(to='e')) > 0


# -- what the notebook user is told ----------------------------------------------

def test_the_parameters_it_used_are_reported_with_their_defaults():
    setup = teaching_setup()
    used = {use.name: use for use in setup.parameters}
    # only what was actually read: the caller supplied the source here, so the
    # instrument's own wavelength bounds were never consulted
    assert set(used) == {'chopperspeed', 'chopperdelay'}
    assert used['chopperspeed'].value == pytest.approx(14.0)
    assert used['chopperspeed'].unit == 'Hz'
    assert used['chopperspeed'].used_by == ('chopper.speed',)
    # an instrument niess built carries its own values, so nothing has to be supplied
    assert not any(use.overridden for use in setup.parameters)
    assert 'nothing has to be provided' in repr(setup)


def test_the_wavelength_bounds_are_read_when_the_source_is_built_here():
    """And not when it is not -- the report is what was used, not what exists."""
    from niess.teaching import Primary
    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    Primary.from_calibration().to_mccode(assembler)
    setup = to_tof_model(assembler, source=offline_source())
    assert 'source_lambda_min' not in {use.name for use in setup.parameters}


def test_a_value_can_be_overridden_and_says_so():
    setup = teaching_setup().with_values(chopperspeed=70.0)
    used = {use.name: use for use in setup.parameters}
    assert used['chopperspeed'].value == pytest.approx(70.0)
    assert used['chopperspeed'].overridden
    assert used['chopperspeed'].default == pytest.approx(14.0)
    assert setup.choppers[0].frequency == pytest.approx(70.0)
    assert 'nothing has to be provided' not in repr(setup)


def test_overriding_something_that_is_not_a_parameter_is_refused():
    with pytest.raises(ValueError, match='not instrument parameters'):
        teaching_setup(values={'not_a_knob': 1.0})


def test_a_child_assembler_is_refused():
    """Its parent has not merged it yet, so most of the instrument is not there."""
    from niess.teaching import Primary
    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    Primary.from_calibration().to_mccode(assembler)
    with assembler.included('section') as child:
        with pytest.raises(ValueError, match='top-level Assembler'):
            to_tof_model(child, source=offline_source())


# -- a real instrument -----------------------------------------------------------

def test_bifrost_becomes_a_chopper_cascade_that_chops():
    """Six choppers, four monitors and the sample, and a band actually selected.

    A cascade that let everything through would pass every structural assertion above
    while being useless, so this checks that the train narrows what reaches the sample.
    """
    from niess.bifrost import Primary
    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration().to_mccode(assembler)
    setup = to_tof_model(assembler, source=offline_source())

    assert len(setup.choppers) == 6
    assert setup.detectors[-1] == 'sample_origin'
    # in beam order, which is what a cascade diagram is read along
    assert [c.distance for c in setup.choppers] == sorted(c.distance for c in setup.choppers)

    result = setup.model.run()
    reaching = {name: int(result.detectors[name].toa.data.sum().value)
                for name in setup.detectors}
    assert reaching['sample_origin'] < reaching[setup.detectors[0]]
    assert reaching['sample_origin'] > 0


def test_the_facility_profile_follows_the_instrument_name(monkeypatch):
    """`bifrost` has its own pulse profile; `teaching` does not, and falls back."""
    from niess.tof.setup import _facility_for

    class Fake:
        def __init__(self, name):
            self.name = name

    import tof as real
    assert _facility_for(Fake('bifrost'), real) == 'ess-bifrost'
    assert _facility_for(Fake('cspec'), real) == 'ess-cspec'
    assert _facility_for(Fake('teaching'), real) == 'ess'


# -- instruments that move --------------------------------------------------------

def movable_instrument():
    """A monitor placed against a run-time angle, as a rotating detector tank is."""
    from mccode_antlr.common import Expr, InstrumentParameter
    assembler = Assembler('movable', flavor=Flavor.MCSTAS)
    assembler.parameter(InstrumentParameter.parse('a4/"degree"=90'))
    assembler.parameter('source_lambda_min/"angstrom"=0.75')
    assembler.parameter('source_lambda_max/"angstrom"=10.0')
    assembler.component('source', 'ESS_butterfly', at=((0, 0, 0), 'ABSOLUTE'),
                        parameters={'Lmin': 'source_lambda_min',
                                    'Lmax': 'source_lambda_max'})
    disc(14.0).to_mccode(assembler, at='source', rotate='source')
    fixed = assembler.component('fixed_monitor', 'TOF_monitor',
                                at=((0, 0, 8.0), 'source'))
    turntable = assembler.component('turntable', 'Arm', at=((0, 0, 9.0), 'source'),
                                    rotate=((0, Expr.parameter('a4'), 0), 'source'))
    assembler.component('moving_monitor', 'TOF_monitor', at=((0, 0, 1.0), turntable))
    return assembler


def test_a_component_that_moves_is_left_out_rather_than_fatal():
    """Its distance along the beam is not a number until the simulation runs.

    `tof` flies neutrons to a fixed distance, so it has nothing to say about a detector on
    a tank that rotates -- but the rest of the instrument is still worth modelling, and
    used to be lost with it.
    """
    setup = to_tof_model(movable_instrument(), source=offline_source())
    assert 'fixed_monitor' in setup.detectors
    assert 'moving_monitor' not in setup.detectors
    assert len(setup.choppers) == 1
    assert any('moving_monitor' in note for note in setup.notes)


def test_the_last_detector_is_the_furthest_that_can_be_measured():
    """Not the beam path's end, which on a moving instrument cannot be placed.

    `turntable` is the furthest point that still can be: only its *rotation* depends on
    the run-time angle, so it sits at a known distance, and the monitor mounted on it does
    not. On BIFROST the same rule picks `sample_origin`, which is likewise an Arm.
    """
    setup = to_tof_model(movable_instrument(), source=offline_source())
    assert setup.detectors[-1] == 'turntable'
    assert 'moving_monitor' not in setup.detectors


def test_an_expression_that_does_not_reduce_says_so_as_a_value_error():
    """`Expr.value` raises NotImplementedError, and `hasattr` does not catch it.

    So asking whether an expression had a value used to raise straight through every
    caller -- and every caller in niess spells "this names a run-time parameter, skip it"
    as catching TypeError/ValueError.
    """
    from mccode_antlr.common.expression import Expr
    from niess.dispatch import expr_float

    assert expr_float(Expr.parse('3 * 4')) == pytest.approx(12.0)
    with pytest.raises(ValueError):
        expr_float(Expr.parse('a4 * 2'))


# -- values arrive with their own units -------------------------------------------

@pytest.mark.parametrize('given,expected', [
    (70.0, 70.0),
    (sc.scalar(70.0, unit='Hz'), 70.0),
    (sc.scalar(0.07, unit='kHz'), 70.0),
])
def test_a_speed_is_converted_to_what_the_instrument_declares(given, expected):
    """A calculator is entitled to hand back kHz; the instrument says Hz."""
    setup = teaching_setup(values={'chopperspeed': given})
    assert setup.choppers[0].frequency == pytest.approx(expected)


def test_a_delay_in_milliseconds_is_converted_to_seconds():
    setup = teaching_setup(values={'chopperdelay': sc.scalar(17.0, unit='ms')})
    assert setup.choppers[0].phase == pytest.approx(delay_to_phase(0.017, 14.0))
    assert next(u for u in setup.parameters
                if u.name == 'chopperdelay').value == pytest.approx(0.017)


def test_a_value_in_the_wrong_unit_is_refused_by_name():
    with pytest.raises(ValueError, match="chopperspeed is declared in 'Hz'"):
        teaching_setup(values={'chopperspeed': sc.scalar(1.0, unit='m')})


# -- a beam that branches ---------------------------------------------------------

def branching_instrument():
    """The beam splits at the sample; declaration order would chain the two detectors."""
    assembler = Assembler('branch', flavor=Flavor.MCSTAS)
    assembler.parameter('source_lambda_min/"angstrom"=0.75')
    assembler.parameter('source_lambda_max/"angstrom"=10.0')
    assembler.component('source', 'ESS_butterfly', at=((0, 0, 0), 'ABSOLUTE'),
                        parameters={'Lmin': 'source_lambda_min',
                                    'Lmax': 'source_lambda_max'})
    disc(14.0).to_mccode(assembler, at='source', rotate='source')
    assembler.component('sample', 'Arm', at=((0, 0, 10.0), 'source'))
    assembler.component('east', 'TOF_monitor', at=((3.0, 0, 0), 'sample'))
    assembler.component('west', 'TOF_monitor', at=((-3.0, 0, 0), 'sample'))

    from networkx import DiGraph
    flow = DiGraph()
    flow.add_edges_from([('source', 'pack_slit_0'), ('pack_slit_0', 'pack_slit_1'),
                         ('pack_slit_1', 'pack_slit_2'), ('pack_slit_2', 'sample'),
                         ('sample', 'east'), ('sample', 'west')])
    return assembler, flow


def placed_detectors(setup):
    return {name: setup.model.detectors[name].distance.value for name in setup.detectors}


def test_distances_follow_the_declared_order_without_a_graph():
    """Which chains the two detectors, so the second is measured through the first.

    `west` comes out 6 m further than `east` -- back to the sample and out the other side
    -- when they are the same distance from it.
    """
    assembler, _ = branching_instrument()
    placed = placed_detectors(to_tof_model(assembler, source=offline_source()))
    assert placed['west'] - placed['east'] == pytest.approx(6.0, abs=1e-9)


def test_a_given_graph_measures_each_branch_from_where_it_leaves():
    """Both detectors are 3 m off the same sample, so both are the same distance away."""
    assembler, flow = branching_instrument()
    placed = placed_detectors(
        to_tof_model(assembler, source=offline_source(), graph=flow))
    assert placed['west'] == pytest.approx(placed['east'], abs=1e-9)


def test_the_graph_reaches_the_chopper_train_too():
    """`build_train` walks the same flow, so a chopper's path has to come from it.

    This one is upstream of the branch, so the two graphs agree about it -- which is the
    point: handing in a graph must not disturb what was already right.
    """
    assembler, flow = branching_instrument()
    without = to_tof_model(assembler, source=offline_source())
    given = to_tof_model(assembler, source=offline_source(), graph=flow)
    assert len(given.choppers) == 1
    assert given.choppers[0].distance == pytest.approx(without.choppers[0].distance,
                                                       abs=1e-12)
