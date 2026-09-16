"""Converting a `.instr` into a niess submodule.

The gate throughout is the one `docs/how-to/translate-an-instr.md` insists on: not
whether the generated text looks right, but whether every component ends up where the
instrument it was converted from puts it.
"""
import pytest

from niess.io.mccode import load_instr
from niess.mccode import to_mccode
from niess.scaffold import (
    check_against_mccode, compare, convert, summary, to_instrument, write,
)
from niess.scaffold.verify import has_symbolic_rotation

TEACHING = 'docs/examples/teaching_hand_written.instr'


@pytest.fixture(scope='module')
def teaching():
    from pathlib import Path
    return load_instr(Path(TEACHING).resolve())


@pytest.fixture(scope='module')
def foreign():
    """A real McCode example: 50 components, 22 symbolic placements, 42 of them
    components niess has no class for."""
    from pathlib import Path
    path = Path(__file__).parent / 'data' / 'ESS_IN5_reprate.instr'
    try:
        return load_instr(path)
    except Exception as error:  # component registry unreachable
        pytest.skip(f'cannot resolve components for {path.name}: {error}')


# --- the placement machinery -------------------------------------------------------

def test_placements_agree_with_mccode(teaching):
    """`placements` against an independent implementation of the same arithmetic.

    Both sides of `compare` are measured with `placements`, so this is what stops that
    from being merely self-consistent.
    """
    assert not has_symbolic_rotation(teaching)
    assert check_against_mccode(teaching).ok


def test_the_reference_for_mccodes_own_resolution_is_refused_when_it_is_wrong(foreign):
    """`resolve_orientations` loses the degrees-to-radians conversion on a symbolic
    angle, so it is not a valid reference for an instrument that has one."""
    assert has_symbolic_rotation(foreign)
    with pytest.raises(ValueError, match='symbolic ROTATED'):
        check_against_mccode(foreign)


# --- conversion --------------------------------------------------------------------

def test_the_teaching_instrument_converts_to_the_same_places(teaching):
    converted = to_mccode(to_instrument(convert(teaching, origin='sample_origin')))
    comparison = compare(teaching, converted)
    assert comparison.ok, comparison.report()
    assert len(comparison.matched) == 7


def test_a_foreign_instrument_converts_to_the_same_places(foreign):
    converted = to_mccode(to_instrument(convert(foreign, origin='sample')))
    comparison = compare(foreign, converted)
    assert comparison.ok, comparison.report()
    assert len(comparison.matched) == 50


def test_what_is_modelled_and_what_is_not(teaching):
    conversion = convert(teaching, origin='sample_origin')
    mapped = {m.name: m.niess_class.__name__ for m in conversion.components}
    assert mapped == {
        'source': 'ESSource',
        'unit_1': 'StraightGuide',
        'unit_2': 'StraightGuide',
        'chopper': 'DiscChopper',
        'jaw': 'Jaw',
        'monitor': 'Opaque',      # every niess monitor emits Frame_monitor, so a
        'sample_origin': 'Component',  # TOF_monitor cannot be inverted to one of them
    }


def test_an_unrecognised_component_becomes_opaque_rather_than_an_arm(foreign):
    """The failure this whole design exists to prevent."""
    conversion = convert(foreign)
    opaque = {m.name: m for m in conversion.opaque}
    assert 'Origin' in opaque
    assert opaque['Origin'].calibration['mccode_type'] == 'Progress_bar'
    assert len(conversion.opaque) == 42


def test_a_parameter_the_component_declares_itself_is_not_carried_forward(teaching):
    """Two declarations of one name collide and the module would not build."""
    conversion = convert(teaching, origin='sample_origin')
    assert conversion.subsumed == {
        'chopperspeed': 'chopper', 'chopperdelay': 'chopper',
        'jaw_l': 'jaw', 'jaw_r': 'jaw',
    }
    assert conversion.parameters == ()

    # the signature is unchanged: the names still exist, declared by their components
    emitted = to_mccode(to_instrument(conversion))
    assert sorted(p.name for p in emitted.parameters) == [
        'chopperdelay', 'chopperspeed', 'jaw_l', 'jaw_r',
    ]


def test_parameters_that_drove_geometry_are_recorded_as_frozen(foreign):
    conversion = convert(foreign)
    assert conversion.frozen['GUI_start'] == pytest.approx(2.0)
    assert conversion.frozen['TT'] == pytest.approx(50.0)
    # a parameter that never appears in a placement is not frozen
    assert 'Lmin' not in conversion.frozen


# --- recipes -----------------------------------------------------------------------

def test_a_guide_is_straight_or_tapered_by_its_parameters(teaching):
    from niess.components import StraightGuide
    conversion = convert(teaching)
    guide = next(m for m in conversion.components if m.name == 'unit_1')
    assert guide.niess_class is StraightGuide
    # `Guide_gravity` reads a negative face m-value as "use m", and its default is -1
    assert guide.calibration['m'] == pytest.approx(2.0)
    assert 'left' not in guide.calibration


def test_a_slit_is_a_jaw_only_when_this_instance_drives_its_edges(teaching):
    from niess.components import Aperture, Jaw
    from niess.scaffold.recipes import slit

    conversion = convert(teaching)
    jaw = next(m for m in conversion.components if m.name == 'jaw')
    assert jaw.niess_class is Jaw

    # the same component type with fixed edges is a plain Aperture
    instance = teaching.get_component('jaw')
    fixed = instance.copy()
    fixed.set_parameters(xwidth=0.03, yheight=0.05)
    fixed.parameters = tuple(p for p in fixed.parameters if p.name not in ('xmin', 'xmax'))
    from niess.scaffold.fold import folder
    assert slit(fixed, folder(teaching))[0] is Aperture


def test_a_disc_chopper_is_placed_by_its_spindle(teaching):
    """`position` is the spindle; the `.instr` gave the beam crossing.

    Reading the `AT` as the position would put the disc off the beam, where it absorbs
    every neutron without saying so.
    """
    conversion = convert(teaching, origin='sample_origin')
    chopper = next(m for m in conversion.components if m.name == 'chopper')
    offset = chopper.position_offset.to(unit='m').value
    # radius - yheight/2, below the beam, exactly McStas' own `delta_y`
    assert offset[1] == pytest.approx(-(0.35 - 0.06 / 2))
    assert offset[0] == pytest.approx(0.0) and offset[2] == pytest.approx(0.0)


def test_a_recipe_that_cannot_cope_falls_back_rather_than_failing(teaching):
    """Returning `None` -- or raising -- is a component that becomes `Opaque`, never a
    conversion that stops."""
    from niess.scaffold import recipes

    def unhappy(instance, fold):
        raise RuntimeError('nope')

    original = dict(recipes.RECIPES)
    recipes.RECIPES['Guide_gravity'] = unhappy
    try:
        conversion = convert(teaching)
        guide = next(m for m in conversion.components if m.name == 'unit_1')
        assert guide.is_opaque
        assert guide.calibration['mccode_type'] == 'Guide_gravity'
    finally:
        recipes.RECIPES.clear()
        recipes.RECIPES.update(original)


# --- generated source --------------------------------------------------------------

def _load_generated(package):
    import importlib.util
    import sys

    name = package.name
    spec = importlib.util.spec_from_file_location(name, package / '__init__.py',
                                                  submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize('fixture,origin,count',
                         [('teaching', 'sample_origin', 7), ('foreign', 'sample', 50)])
def test_the_generated_module_builds_and_places_everything(fixture, origin, count,
                                                           tmp_path, request):
    instr = request.getfixturevalue(fixture)
    conversion = convert(instr, origin=origin)
    package = write(conversion, tmp_path)

    module = _load_generated(package)
    comparison = compare(instr, to_mccode(module.instrument()))
    assert comparison.ok, comparison.report()
    assert len(comparison.matched) == count


def test_the_generated_module_keeps_the_instr_and_a_test_beside_it(teaching, tmp_path):
    from pathlib import Path
    conversion = convert(teaching, origin='sample_origin')
    package = write(conversion, tmp_path, instr_path=Path(TEACHING).resolve())
    assert (package / 'teaching_hand_written.instr').is_file()
    assert (package / 'test_placement.py').is_file()
    assert {p.name for p in package.glob('*.py')} == {
        '__init__.py', 'parameters.py', 'structure.py', 'instrument.py',
        'test_placement.py',
    }


def test_a_folded_parameter_comes_back_as_a_named_constant(foreign, tmp_path):
    """The number is the calibration; the name is the structure the author meant."""
    package = write(convert(foreign), tmp_path)
    text = (package / 'parameters.py').read_text()
    assert 'GUI_start = 2.0' in text
    assert "vector([0.0, 0.0, GUI_start], unit='m')" in text


def test_the_chain_hangs_off_the_instrs_placement_not_the_niess_one(teaching, tmp_path):
    """Everything after a disc chopper still hangs off the beam crossing.

    Chaining off the spindle instead carries the chopper's offset into every later
    component -- the error `translate-an-instr.md` warns about, and one a literal
    transcription *can* make once a recipe introduces a reference-point offset.
    """
    package = write(convert(teaching, origin='sample_origin'), tmp_path)
    text = (package / 'parameters.py').read_text()
    assert "at_relative(at['unit_2']" in text
    assert "'position': at['chopper'] + vector(" in text


def test_the_report_names_the_work_that_is_left(foreign):
    text = summary(convert(foreign))
    assert '8 of 50 components were mapped' in text
    assert 'L_monitor' in text and 'to-do list' in text
    assert 'GUI_start' in text
