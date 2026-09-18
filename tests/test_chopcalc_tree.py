"""The chopper train, read off the tree instead of off an emitted instrument.

`niess.chopcalc.discovery` reads the components McStas was given, recovering which disc
is which, where a multi-opening one came apart, and which knob sets its speed. Reading
the tree, a disc is a disc. These check the two agree, because the emitted C has to be
the same either way -- `emit.py` is untouched and takes whichever train it is handed.
"""
import pytest

from niess.chopcalc.discovery import build_train
from niess.chopcalc.tree import train_from_instrument
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


def test_the_two_routes_find_the_same_choppers(bifrost_primary):
    """The acceptance test: same discs, same knobs, same windows, same path lengths.

    Every field is C text, so this is an exact comparison of what reaches the generated
    instrument -- not of two numbers that happen to round the same way.
    """
    from_instrument = build_train(assembled(bifrost_primary()).instrument)
    from_tree = train_from_instrument(Instrument(
        name='bifrost', parts=(Mount(name='primary', content=bifrost_primary()),)))

    assert len(from_tree.choppers) == 6
    assert from_tree.choppers == from_instrument.choppers


def test_the_two_routes_narrow_the_same_band(bifrost_primary):
    """Same lambda knobs, and the same latest emission time.

    The expression differs and the value does not. Reading an instrument picks up
    ESS_butterfly's own default of tmax_multiplier=3 and writes `3.0 * 0.002857`;
    reading the tree finds no latest_emission_time set and falls back to niess' own
    default, which is three ESS pulses -- the same 0.008571 s, honestly labelled.
    """
    from_instrument = build_train(assembled(bifrost_primary()).instrument).source
    from_tree = train_from_instrument(Instrument(
        name='bifrost', parts=(Mount(name='primary', content=bifrost_primary()),))).source

    assert from_tree.lambda_min == from_instrument.lambda_min
    assert from_tree.lambda_max == from_instrument.lambda_max
    assert from_tree.name == from_instrument.name
    assert eval(from_tree.latest_emission) == pytest.approx(
        eval(from_instrument.latest_emission), rel=1e-4)


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


def test_the_generated_c_is_the_same_either_way(bifrost_primary):
    """emit.py is untouched, and takes whichever train it is handed."""
    from niess.chopcalc import narrow_source_wavelengths

    def narrowed(train):
        assembler = assembled(bifrost_primary())
        narrow_source_wavelengths(assembler, train=train)
        text = str(assembler.instrument)
        return text[text.index('DEFINE INSTRUMENT'):]

    tree = train_from_instrument(Instrument(
        name='bifrost', parts=(Mount(name='primary', content=bifrost_primary()),)))
    from_tree = narrowed(tree).split('\n')
    from_instrument = narrowed(None).split('\n')

    differing = [(a, b) for a, b in zip(from_instrument, from_tree) if a != b]
    assert len(from_tree) == len(from_instrument)
    # only the latest-emission line, and only in how the same value is written
    assert len(differing) == 1
    assert 'chopcalc_latest' in differing[0][0]


def test_a_chopper_in_a_mounted_frame_is_refused(bifrost_primary):
    """Rather than measuring the beam path from the wrong origin.

    Nothing before the sample needs composed frames, so nothing composes them; a disc
    that did would be measured against the instrument origin and silently be wrong.
    """
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    from niess.chopcalc.discovery import ChopcalcError
    from niess.chopcalc.tree import _global_position
    from niess.walk import visits

    instrument = Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=bifrost_primary()),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin'),
    ))
    inside = next(v for v in visits(instrument) if v.id == 'tank/monitor')
    with pytest.raises(ChopcalcError, match='measured in the instrument frame'):
        _global_position(inside)
