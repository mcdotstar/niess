"""The chopper train, read off the tree instead of off an emitted instrument.

`niess.chopcalc` used to have a second route that read the components McStas was given,
recovering which disc
is which, where a multi-opening one came apart, and which knob sets its speed. Reading
the tree, a disc is a disc. These check the two agree, because the emitted C has to be
the same either way -- `emit.py` is untouched and takes whichever train it is handed.
"""
import pytest

from niess.chopcalc import train_from_instrument
from niess.instrument import Instrument, Mount


def assembled(*parts):
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    for part in parts:
        part.to_mccode(assembler)
    return assembler


@pytest.fixture(scope='module')
def teaching():
    from niess.teaching import Primary
    return Primary


@pytest.fixture(scope='module')
def bifrost_primary():
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    return lambda: Primary.from_calibration(primary_parameters())


def test_the_train_of_bifrost_is_what_it_is(bifrost_primary):
    """What the two routes used to be compared against each other for.

    The instrument-reading route is gone, so there is nothing left to compare with --
    these are the values the comparison agreed on, written down. Six discs in beam
    order, and a band written through the source's own two knobs rather than as numbers
    the instrument would then contradict.
    """
    train = train_from_instrument(Instrument(
        name='bifrost', parts=(Mount(name='primary', content=bifrost_primary()),)))

    assert [c.name for c in train.choppers] == [
        'pulse_shaping_chopper_1', 'pulse_shaping_chopper_2',
        'frame_overlap_chopper_1', 'frame_overlap_chopper_2',
        'bandwidth_chopper_1', 'bandwidth_chopper_2',
    ]
    assert train.source.name == 'source'
    assert train.source.lambda_min == 'source_lambda_min'
    assert train.source.lambda_max == 'source_lambda_max'
    assert float(train.source.latest_emission) == pytest.approx(3.0 * 0.002857)


def test_a_disc_is_a_disc(teaching):
    """No group tags, no metadata, no putting anything back together."""
    train = train_from_instrument(Instrument(
        name='teaching', parts=(Mount(name='primary', content=teaching.from_calibration()),)))
    entry, = train.choppers
    assert entry.name == 'chopper'
    assert entry.speed == 'chopperspeed'
    assert entry.delay == 'chopperdelay'
    assert entry.windows == (('-85.0', '85.0'),)


def test_a_multi_opening_disc_keeps_all_its_windows():
    """Which the other route recovers by grouping components on a metadata tag."""
    from scipp import array, scalar, vector
    from scipp.spatial import rotations_from_rotvecs
    from niess.components import DiscChopper, ESSource, Section
    from niess.teaching.parameters import teaching_parameters

    source = ESSource.from_calibration(teaching_parameters()['source'])
    disc = DiscChopper.from_calibration({
        'name': 'pack', 'position': vector([0, 0, 5.0], unit='m'),
        'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
        'radius': scalar(0.35, unit='m'), 'height': scalar(0.06, unit='m'),
        'frequency': scalar(14.0, unit='Hz'),
        'top_dead_center': scalar(0.0, unit='deg'),
        'beam_position': scalar(0.0, unit='deg'),
        'windows': array(values=[10., 30., 100., 140.], dims=['edges'], unit='deg'),
    })

    class Chopped(Section):
        source: ESSource
        pack: DiscChopper
        _flat: bool = True

    train = train_from_instrument(Instrument(
        name='chopped', parts=(Mount(name='s', content=Chopped(source=source, pack=disc)),)))
    entry, = train.choppers
    assert len(entry.windows) == 2, 'both openings, from the disc itself'




def test_a_chopper_in_a_mounted_frame_is_refused(bifrost_primary):
    """Rather than measuring the beam path from the wrong origin.

    Nothing before the sample needs composed frames, so nothing composes them; a disc
    that did would be measured against the instrument origin and silently be wrong.
    """
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    from niess.chopcalc import ChopcalcError
    from niess.chopcalc.paths import global_position
    from niess.walk import visits

    instrument = Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=bifrost_primary()),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin'),
    ))
    inside = next(v for v in visits(instrument) if v.id == 'tank/monitor')
    with pytest.raises(ChopcalcError, match='measured in the instrument frame'):
        global_position(inside)
