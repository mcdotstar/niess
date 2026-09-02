"""Only simulate the wavelengths a chopper train can pass.

A source samples uniformly across the band it is given and a chopper train throws most of
that away, so narrowing the source to the band the train passes is free simulation speed.
The band depends on chopper speeds and delays, which are run-time parameters, so it cannot
be computed when the instrument is built -- hence C, emitted into the instrument's
INITIALIZE, which McCode runs before every component's own initialisation. That ordering
is the whole trick, and it is why these tests assert against generated text.

The version this replaces lived inline in a BIFROST build script. It walked the top level
of a niess Section tree, so it found 2 of BIFROST's 6 choppers and narrowed the band to
[0.75, 10.45] A where the full train admits [0.75, 0.81] A -- safe, since an over-wide
band only wastes time, but most of the speed-up was left behind.
"""
import logging

import pytest
from mccode_antlr import Flavor
from mccode_antlr.assembler import Assembler
from scipp import array, scalar

from niess.chopcalc import ChopcalcError, narrow_source_wavelengths

EDGES = [10.0, 30.0, 100.0, 140.0, 350.0, 370.0]


def source_at(assembler, *, lmin='source_lambda_min', lmax='source_lambda_max',
              declare=True, **extra):
    if declare:
        assembler.parameter(f'{lmin}/"angstrom"=0.75')
        assembler.parameter(f'{lmax}/"angstrom"=30.0')
    return assembler.component(
        'source', 'ESS_butterfly', at=((0, 0, 0), 'ABSOLUTE'),
        parameters={'Lmin': lmin, 'Lmax': lmax, **extra})


def one_chopper(**overrides):
    """A source and a single DiskChopper, with nothing else in the way."""
    assembler = Assembler('bare', flavor=Flavor.MCSTAS)
    source_at(assembler)
    parameters = {'theta_0': 170.0, 'nslit': 1, 'radius': 0.35, 'yheight': 0.06,
                  'nu': 'chopperspeed', 'delay': 'chopperdelay'}
    parameters.update(overrides)
    assembler.parameter('chopperspeed/"Hz"=14.0')
    assembler.parameter('chopperdelay/"s"=0.0')
    assembler.component('chopper', 'DiskChopper', at=((0, 0, 6.0), 'source'),
                        parameters=parameters)
    return assembler


def multi_slit(edges=EDGES):
    """A source and one disc with several openings, as a tree."""
    from niess.components import DiscChopper
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs
    disc = DiscChopper.from_calibration({
        'name': 'pack',
        'position': vector([0, 0, 6.0], unit='m'),
        'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
        'radius': scalar(0.35, unit='m'), 'height': scalar(0.06, unit='m'),
        'frequency': scalar(14.0, unit='Hz'),
        'beam_position': scalar(90.0, unit='deg'),
        'windows': array(values=edges, dims=['edges'], unit='deg'),
    })
    return _built('disc', _bare_source(), disc)


def _bare_source(lmin=0.75, lmax=30.0):
    """A moderator whose band the narrowing writes through."""
    from niess.components.source import ESSource
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs
    return ESSource.from_calibration({
        'name': 'source',
        'position': vector([0, 0, 0.], unit='m'),
        'orientation': rotations_from_rotvecs(vector([0, 0, 0.], unit='deg')),
        'wavelength_minimum': f'source_lambda_min/"angstrom" = {lmin}',
        'wavelength_maximum': f'source_lambda_max/"angstrom" = {lmax}',
    })


def _built(name, *parts):
    """An emitted instrument, carrying the train read off the tree it came from.

    Narrowing is emission and no longer finds its own train -- reading one back out of
    an assembled instrument is what the demotion removed -- so the tree that produced
    the instrument produces the train alongside it.
    """
    from niess.chopcalc import train_from_instrument
    from niess.instrument import Instrument, Mount
    from niess.mccode import to_mccode

    tree = Instrument(name=name, parts=tuple(
        Mount(name=getattr(part, 'name', f'part{i}'), content=part)
        for i, part in enumerate(parts)))
    assembler = Assembler(name, flavor=Flavor.MCSTAS)
    to_mccode(tree, assembler=assembler)
    assembler.chopper_train = train_from_instrument(tree)
    return assembler


def narrow(built, **kwargs):
    """`narrow_source_wavelengths` for a fixture that carries its own train."""
    return narrow_source_wavelengths(built, built.chopper_train, **kwargs)


@pytest.fixture
def teaching():
    from niess.teaching import Primary
    return _built('teaching', Primary.from_calibration())


@pytest.fixture
def bifrost():
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    return _built('bifrost', Primary.from_calibration(primary_parameters()))


# -- what it emits -----------------------------------------------------------

def test_the_band_is_narrowed_through_the_sources_own_parameters(teaching):
    narrow(teaching)
    text = str(teaching.instrument)
    assert '&source_lambda_min, &source_lambda_max' in text
    assert 'chopper_wavelength_limits' in text


def test_a_chopper_is_named_not_valued(teaching):
    """The row references run-time parameters, so the band recomputes without a rebuild."""
    narrow(teaching)
    assert 'chopcalc_choppers[0] = (multi_chopper_parameters){chopperspeed, ' \
           'chopperdelay, 1,' in str(teaching.instrument)


def test_a_single_opening_disc_is_one_window_either_side_of_zero(teaching):
    """A DiskChopper opening is centred on the path at its delay, so its window is too.

    chopper-lib's own ``single_to_multi_chopper`` builds exactly this pair out of a width,
    which is what makes the multi-opening calculation give a plain disc the answer the
    single-opening one used to give it.
    """
    train = narrow(teaching)
    chopper = next(c for c in train.choppers if c.name == 'chopper')
    assert chopper.windows == (('-85.0', '85.0'),)   # theta_0 = 170 degrees
    assert 'chopcalc_choppers[0].windows[0] = (chopper_window){-85.0, 85.0};' \
           in str(teaching.instrument)


def test_every_chopper_is_found_however_deeply_it_is_nested(bifrost):
    """BIFROST hides four of its six choppers inside nested Sections.

    The version this replaces walked ``Primary.items()``, which reaches only top-level
    fields, and so never saw the frame-overlap or bandwidth pairs -- the ones that
    actually set the band.
    """
    train = narrow(bifrost)
    assert [c.name for c in train.choppers] == [
        'pulse_shaping_chopper_1', 'pulse_shaping_chopper_2',
        'frame_overlap_chopper_1', 'frame_overlap_chopper_2',
        'bandwidth_chopper_1', 'bandwidth_chopper_2',
    ]


def test_the_choppers_come_out_in_beam_order(bifrost):
    train = narrow(bifrost)
    paths = [float(c.path) for c in train.choppers]
    assert paths == sorted(paths)


def test_the_path_is_walked_along_the_beam(bifrost):
    """Not chorded from the origin: a curved guide is followed, not cut across."""
    train = narrow(bifrost)
    walked = {c.name: float(c.path) for c in train.choppers}
    # the bandwidth choppers sit 78 m away past the curved section
    assert walked['bandwidth_chopper_1'] > 77.98
    assert walked['bandwidth_chopper_1'] < 78.0


def test_the_latest_emission_time_comes_from_the_source_itself(teaching):
    """Not the hardcoded 2.0e-4 + 2.86e-3 + 2e-3 the previous version carried.

    The number is the same one the instrument-reading route worked out, and it is now
    worked out rather than written as `3.0 * 0.002857`: that route read the emitted
    component's own `tmax_multiplier` default, and the tree has the source instead. A
    source that states a `latest_emission_time` still overrides it.
    """
    train = narrow(teaching)
    assert float(train.source.latest_emission) == pytest.approx(3.0 * 0.002857)
    assert '3 ESS pulses' in train.source.latest_emission_note






def test_the_include_is_guarded_against_an_older_chopper_lib(teaching):
    """Neither meaning change altered a struct's size, so only a guard catches them.

    2.0.0 turned the second field from a phase in degrees into a delay in seconds; 3.0.0
    started placing a window angle with the signed speed. An older library compiles either
    one cleanly and computes a different band.
    """
    narrow(teaching)
    text = str(teaching.instrument)
    assert '%include "chopper-lib"' in text
    assert 'CHOPPER_LIB_VERSION < 30000' in text
    assert '#error' in text


def test_the_registry_is_added_once(teaching):
    narrow(teaching)
    names = [r.name for r in teaching.instrument.registries]
    assert names.count('mcstas-chopper-lib') == 1


def test_calling_it_twice_does_not_narrow_twice(teaching, caplog):
    assert narrow(teaching) is not None
    with caplog.at_level(logging.WARNING):
        assert narrow(teaching) is None
    assert 'already been narrowed' in caplog.text
    assert str(teaching.instrument).count(
        'multi_chopper_parameters * chopcalc_choppers') == 1


# -- publishing the train for a component to read -----------------------------

def test_the_train_can_be_published_for_a_component_to_read(teaching):
    """A component that takes the train needs it to outlive INITIALIZE.

    The narrowing builds its array inside a braced block, which is what keeps its own
    names from colliding with anything else in INITIALIZE -- and also means the array and
    its window arrays are gone by the time any component runs. Publishing puts a copy at
    file scope instead.
    """
    train = narrow(teaching, export_choppers='train', strict=True)
    assert train.export.choppers == 'train'
    assert train.export.count == 'train_count'

    text = str(teaching.instrument)
    assert 'multi_chopper_parameters * train = NULL;' in text
    assert 'int train_count = 0;' in text
    # the train is built on the heap either way, so handing it over is an assignment
    assert 'train = chopcalc_choppers;' in text
    assert 'train_count = 1;' in text
    assert 'free(train);' in text
    assert 'train = NULL;' in text


def test_publishing_moves_the_release_rather_than_copying_the_train(teaching):
    """The train is on the heap whether or not anything else reads it.

    That is the point of building it there: publishing is then a pointer assignment, and
    the release is the same few lines wherever it ends up. Without an export they run at
    the end of INITIALIZE; with one they run in FINALLY, and nowhere else.
    """
    plain = narrow(teaching)
    kept = str(teaching.instrument)

    from niess.teaching import Primary
    other = _built('teaching', Primary.from_calibration())
    narrow(other, export_choppers='train', strict=True)
    published = str(other.instrument)

    assert plain.export is None
    # the same release, once each, on whichever name owns the train
    release = 'free(chopcalc_choppers);'
    assert kept.count(release) == 1
    assert published.count(release) == 0
    assert published.count('free(train);') == 1
    # each row's openings go back before the row array, or they would leak with it
    assert 'free(chopcalc_choppers[chopcalc_i].windows);' in kept
    assert 'free(train[chopcalc_i].windows);' in published
    # and nothing is copied to get there
    assert 'windows[chopcalc_w]' not in published


def test_the_count_can_be_named(teaching):
    train = narrow(
        teaching, export_choppers='train', export_chopper_count='how_many', strict=True)
    assert train.export.count == 'how_many'
    assert 'int how_many = 0;' in str(teaching.instrument)


def test_nothing_is_published_unless_it_is_asked_for(teaching):
    """The default stays a self-contained block: no DECLARE storage, no FINALLY."""
    train = narrow(teaching)
    assert train.export is None
    text = str(teaching.instrument)
    # the train itself is still a heap local; what is absent is file-scope storage for it
    assert 'multi_chopper_parameters * chopcalc_choppers' in text
    assert '= NULL;\nint ' not in text
    assert 'FINALLY' not in text


@pytest.mark.parametrize('names,complaint', [
    ({'export_chopper_count': 'n'}, 'needs export_choppers'),
    ({'export_choppers': 'not an identifier'}, 'not a C identifier'),
    ({'export_choppers': 'chopcalc_choppers'}, 'reserved'),
    ({'export_choppers': 'source_lambda_min'}, 'already an instrument parameter'),
    ({'export_choppers': 'x', 'export_chopper_count': 'x'}, 'two different variables'),
])
def test_a_name_that_would_not_compile_is_refused(teaching, names, complaint):
    """These become file-scope C, so a bad name is a compile error in generated code.

    That is a much worse place to find out than here, where the message can say which
    argument was wrong and why.
    """
    with pytest.raises(ChopcalcError, match=complaint):
        narrow(teaching, strict=True, **names)


# -- what the generated C does when it fails ---------------------------------

def test_a_train_that_passes_nothing_leaves_the_band_alone(teaching):
    """multi_chopper_wavelength_limits leaves its outputs untouched on zero.

    Putting the band back makes that a property of this instrument rather than of
    whichever library version was resolved -- and keeps a degenerate band away from
    ESS_butterfly, whose own INITIALIZE exits when Lmin >= Lmax.
    """
    narrow(teaching)
    text = str(teaching.instrument)
    assert 'chopcalc_bands == 0' in text
    assert 'source_lambda_min = chopcalc_min;' in text


def test_the_advice_names_delays_not_phases(teaching):
    """The version this replaces still said "speeds and phases" after 2.0.0 dropped phase."""
    narrow(teaching)
    text = str(teaching.instrument)
    assert 'chopper speeds and delays' in text
    assert 'phases' not in text


def test_the_envelope_of_several_bands_says_so(teaching):
    narrow(teaching)
    assert 'separate bands' in str(teaching.instrument)


# -- what it refuses ---------------------------------------------------------



def test_an_instrument_with_no_choppers_emits_nothing(caplog):
    empty = _built('empty', _bare_source())
    with caplog.at_level(logging.WARNING):
        assert narrow(empty) is None
    assert 'nothing to narrow' in caplog.text
    assert 'chopcalc_choppers' not in str(empty.instrument)




def test_it_must_be_given_the_top_level_assembler(teaching):
    with teaching.included('teaching_child') as child:
        with pytest.raises(ChopcalcError, match='top-level Assembler'):
            narrow_source_wavelengths(child, teaching.chopper_train)


# -- finding the source ------------------------------------------------------







# -- multi-slit discs --------------------------------------------------------

def test_a_multi_slit_disc_becomes_one_row_per_opening(caplog):
    """A disc is one chopper with several windows, not several choppers.

    chopper-lib *intersects* the rows it is given, so a row per opening would demand a
    neutron clear every opening at once -- a band too narrow, the one failure that loses
    neutrons. One row carrying every window is the union the disc really is.
    """
    assembler = multi_slit([10.0, 30.0, 40.0, 60.0])
    with caplog.at_level(logging.WARNING):
        train = narrow(assembler)
    assert len(train.choppers) == 1
    disc = train.choppers[0]
    assert disc.name == 'pack'
    assert len(disc.windows) == 2
    # every opening shares the disc's own delay; the windows say where each one sits
    assert disc.delay == 'packdelay'


def test_an_opening_is_measured_from_the_beam_against_the_turn(caplog):
    """chopper-lib puts an edge at angle ``a`` on the beam at ``delay + a/(360*speed)``.

    niess measures a slit edge from the top-dead-centre mark and ``packdelay`` is when the
    disc's ``beam_position`` is on the beam, so ``beam_position`` is chopper-lib's zero
    angle and an edge ``e`` sits at ``beam_position - e``. Subtracting is the whole of it:
    an opening counter-clockwise of the beam is reached by turning clockwise, so it lies
    at a negative angle -- and the pair reverses, the edge that opens last coming first.
    """
    assembler = multi_slit([10.0, 30.0, 40.0, 60.0])   # beam_position is 90 degrees
    with caplog.at_level(logging.WARNING):
        train = narrow(assembler)
    assert train.choppers[0].windows == (('60.0', '80.0'), ('30.0', '50.0'))


def test_the_windows_open_when_the_emitted_diskchoppers_open(caplog):
    """The two descriptions of one disc have to agree, whichever way it turns.

    ``DiscChopper`` emits a GROUP of ``DiskChopper`` instances, each with a delay
    worked out from how far the disc must turn to bring that opening round. chopcalc
    describes the same disc to chopper-lib as angles instead. If they disagree, the band
    is narrowed to something the instrument does not actually pass.
    """
    edges = [10.0, 30.0, 100.0, 140.0, 350.0, 370.0]
    beam = 90.0
    assembler = multi_slit(edges)
    with caplog.at_level(logging.WARNING):
        windows = narrow(assembler).choppers[0].windows

    for speed in (14.0, -14.0, 196.0):
        for delay in (0.0, 0.017):
            period = 1.0 / abs(speed)

            def centred(intervals):
                """Opening centres and half-widths, modulo one turn."""
                return sorted((((a + b) / 2) % period, (b - a) / 2) for a, b in intervals)

            # what McStas sees: each opening's own delay, as DiscChopper computes it
            emitted = []
            for opening, closing in zip(edges[::2], edges[1::2]):
                turn = (beam - (opening + closing) / 2) % 360.0
                centre = delay + ((360.0 - turn) if speed < 0 else turn) / (360.0 * abs(speed))
                half = (closing - opening) / 2 / 360.0 / abs(speed)
                emitted.append((centre - half, centre + half))

            # what chopper-lib sees: an angle, placed with the signed speed
            described = []
            for low, high in windows:
                a = delay + float(low) / 360.0 / speed
                b = delay + float(high) / 360.0 / speed
                described.append((min(a, b), max(a, b)))

            for (want_c, want_h), (got_c, got_h) in zip(centred(emitted), centred(described)):
                assert want_c == pytest.approx(got_c, abs=1e-12)
                assert want_h == pytest.approx(got_h, abs=1e-12)


def test_a_disc_whose_openings_span_a_revolution_still_constrains(caplog):
    """Openings reaching right round the disc are not the same as no disc at all.

    Modelled as one angular envelope this disc covered a whole revolution and so admitted
    everything, which is why it used to be dropped. Its openings are 20, 40 and 20 degrees
    wide -- 80 of 360 -- and describing them individually gets that back.
    """
    assembler = multi_slit(EDGES)
    with caplog.at_level(logging.WARNING):
        train = narrow(assembler)
    assert train is not None
    assert len(train.choppers) == 1
    assert len(train.choppers[0].windows) == 3
    assert not train.excluded
    assert 'full revolution' not in caplog.text






def test_the_caller_is_told_what_was_used_and_what_was_not(caplog):
    """So a build script can assert on the outcome without reading generated C."""
    assembler = multi_slit(EDGES)
    with caplog.at_level(logging.WARNING):
        narrow(assembler)
    assembler = multi_slit([10.0, 30.0, 40.0, 60.0])
    train = narrow(assembler)
    assert train.source.name == 'source'
    assert train.choppers[0].name == 'pack'
    assert len(train.choppers[0].windows) == 2
