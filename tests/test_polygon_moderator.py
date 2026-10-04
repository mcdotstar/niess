"""`PolygonESSModerator`: an opt-in moderator that reads the chopper train itself.

chopper-lib's `Polygon_ESS_butterfly` takes the train as a `double *` and a count. niess
publishes the train through `niess.chopcalc`, so the two have to agree on the names --
and an instrument that names a pointer nobody declared does not compile. These check the
agreement is made for the caller, and that a disagreement fails here rather than in C.

Compiling and running one is not done here, since it needs a C compiler: built by hand,
teaching with this moderator gave the same monitor total as with `ESSModerator` -- the
same count of rays, too, with ``resample=0`` -- and agreed within its error with
``resample=1``, from 40% more rays.
"""
import pytest

PARAMETER_BAND = {
    'wavelength_minimum': 'source_lambda_min/"angstrom" = 0.75',
    'wavelength_maximum': 'source_lambda_max/"angstrom" = 5.0',
}


def polygon_teaching(**options):
    from niess.components import PolygonESSModerator
    from niess.instrument import Instrument, Mount
    from niess.teaching import Primary
    from niess.teaching.parameters import teaching_parameters

    parameters = teaching_parameters()
    parameters['moderator'] = PolygonESSModerator.from_calibration(
        parameters['moderator'] | options)
    return Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(parameters)),))


def emitted(instrument):
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.mccode import to_mccode

    assembler = Assembler(instrument.name, flavor=Flavor.MCSTAS)
    to_mccode(instrument, assembler=assembler)
    return assembler


def moderator_instance(assembler):
    return next(i for i in assembler.instrument.components if i.name == 'moderator')


def parameter(instance, name):
    found = [p for p in instance.parameters if p.name == name]
    return str(found[0].value) if found else None


def test_it_emits_polygon_ess_butterfly_reading_the_train():
    instance = moderator_instance(emitted(polygon_teaching()))
    assert instance.type.name == 'Polygon_ESS_butterfly'
    assert parameter(instance, 'choppers') == '(double *) moderator_choppers'
    assert parameter(instance, 'chopper_count') == 'moderator_choppers_count'


def test_only_what_differs_from_the_component_is_emitted():
    """The component's defaults are its own; repeating them would only be noise."""
    plain = moderator_instance(emitted(polygon_teaching()))
    for name in ('resample', 'use_region', 'path_spread_fraction', 'filename'):
        assert parameter(plain, name) is None, name

    chosen = moderator_instance(emitted(polygon_teaching(
        resample=True, path_spread_fraction=1e-4, filename='region', chopper_train='train')))
    assert parameter(chosen, 'resample') == '1'
    assert float(parameter(chosen, 'path_spread_fraction')) == 1e-4
    assert parameter(chosen, 'filename') == '"region"'
    assert parameter(chosen, 'choppers') == '(double *) train'
    assert parameter(chosen, 'chopper_count') == 'train_count'


def test_the_ess_butterfly_parameters_are_unchanged():
    """It is an ESSModerator with a region; everything else it emits is the same."""
    from niess.components import ESSModerator
    from niess.components import PolygonESSModerator
    from niess.teaching.parameters import teaching_parameters

    calibration = teaching_parameters()['moderator']
    _, plain = ESSModerator.from_calibration(calibration).__mccode__()
    _, polygon = PolygonESSModerator.from_calibration(calibration).__mccode__()
    assert {k: v for k, v in polygon.items() if k in plain} == plain


def test_the_train_is_published_under_the_moderators_names():
    from niess.chopcalc import narrow_source_wavelengths, train_from_instrument

    instrument = polygon_teaching(**PARAMETER_BAND)
    train = train_from_instrument(instrument)
    assert train.source.reads_train == ('moderator_choppers', 'moderator_choppers_count')

    assembler = emitted(instrument)
    narrowed = narrow_source_wavelengths(assembler, train)
    assert (narrowed.export.choppers, narrowed.export.count) == train.source.reads_train
    text = str(assembler.instrument)
    assert 'chopper_parameters * moderator_choppers = NULL;' in text
    assert 'moderator_choppers = chopcalc_choppers;' in text


def test_publishing_under_other_names_is_refused():
    from niess.chopcalc import (ChopcalcError, narrow_source_wavelengths,
                                train_from_instrument)

    instrument = polygon_teaching(**PARAMETER_BAND)
    with pytest.raises(ChopcalcError, match='moderator_choppers'):
        narrow_source_wavelengths(emitted(instrument), train_from_instrument(instrument),
                                  export_choppers='elsewhere')


def test_naming_the_same_names_is_fine():
    from niess.chopcalc import narrow_source_wavelengths, train_from_instrument

    instrument = polygon_teaching(**PARAMETER_BAND)
    narrowed = narrow_source_wavelengths(emitted(instrument),
                                         train_from_instrument(instrument),
                                         export_choppers='moderator_choppers')
    assert narrowed.export.count == 'moderator_choppers_count'


def test_a_train_that_cannot_be_published_raises_even_without_strict():
    """Warning and emitting nothing is safe for ESSModerator, and a compile error here."""
    from niess.chopcalc import (ChopcalcError, narrow_source_wavelengths,
                                train_from_instrument)

    instrument = polygon_teaching(**PARAMETER_BAND)
    nothing = train_from_instrument(instrument, skip=('chopper',))
    with pytest.raises(ChopcalcError, match='no chopper reached the calculation'):
        narrow_source_wavelengths(emitted(instrument), nothing, strict=False)


def test_an_ess_moderator_reads_no_train():
    from niess.chopcalc import train_from_instrument
    from niess.instrument import Instrument, Mount
    from niess.teaching import Primary
    from niess.teaching.parameters import teaching_parameters

    parameters = teaching_parameters()
    parameters['moderator'] |= PARAMETER_BAND
    train = train_from_instrument(Instrument(name='teaching', parts=(
        Mount(name='primary', content=Primary.from_calibration(parameters)),)))
    assert train.source.reads_train is None


def test_it_round_trips_through_json():
    from niess.components import PolygonESSModerator
    from niess.io.json import from_json, to_json

    moderator = PolygonESSModerator.from_calibration(
        {'name': 'moderator', 'resample': True, 'chopper_train': 'train'})
    assert from_json(to_json(moderator)) == moderator


def test_the_other_targets_treat_it_as_a_moderator():
    """They register for ESSModerator or Moderator, and dispatch walks the MRO."""
    from niess.brep.builders import BREP_REGISTRY
    from niess.components import ESSModerator, PolygonESSModerator
    from niess.nexus.structure import NEXUS_REGISTRY

    polygon = PolygonESSModerator.from_calibration({'name': 'moderator'})
    plain = ESSModerator.from_calibration({'name': 'moderator'})
    for registry in (BREP_REGISTRY, NEXUS_REGISTRY):
        assert registry.resolve_for_object(polygon) is registry.resolve_for_object(plain)
        assert registry.resolve_for_object(polygon) is not None
