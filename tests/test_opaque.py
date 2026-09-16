"""A component niess does not model, carried through verbatim.

`Opaque` exists so that converting a foreign `.instr` has somewhere to put the components
niess has no class for. The thing these tests are really guarding is that it stays
*faithful*: the failure it was written to prevent is a component silently degrading to a
bare `Arm`, which is what `Component`'s default `__mccode__` does and which changes what
the instrument means without saying so.
"""
import pytest
from scipp import vector
from scipp.spatial import rotations_from_rotvecs

from niess.components import Opaque
from niess.instrument import Instrument, Mount
from niess.mccode import to_mccode


def unrotated():
    return rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg'))


def one(component):
    """Emit a single component and hand back the `Instance` it became."""
    instrument = Instrument(name='test', origin=component.name,
                            parts=(Mount(name='part', content=component),))
    return to_mccode(instrument).components[0]


@pytest.fixture
def psd():
    return Opaque(
        name='psd',
        position=vector([0, 0, 2.5], unit='m'),
        orientation=unrotated(),
        mccode_type='PSD_monitor',
        mccode_parameters={'nx': 90, 'ny': 90, 'filename': '"psd.dat"'},
    )


def test_the_type_and_parameters_are_what_was_given(psd):
    instance = one(psd)
    assert instance.type.name == 'PSD_monitor'
    assert {p.name: p.value.value for p in instance.parameters} == {
        'nx': 90, 'ny': 90, 'filename': '"psd.dat"',
    }


def test_it_does_not_degrade_to_an_arm(psd):
    """The whole point. `Component.__mccode__` returns `('Arm', {})`; this must not."""
    assert psd.__mccode__() == ('PSD_monitor', {'nx': 90, 'ny': 90, 'filename': '"psd.dat"'})
    assert one(psd).type.name != 'Arm'


def test_it_is_placed_where_it_was_put(psd):
    at, reference = one(psd).at_relative
    assert reference is None
    assert [x.value for x in at] == [0, 0, 2.5]


def test_the_role_says_niess_does_not_know_what_this_is(psd):
    """A target can dispatch on this rather than discovering there is no geometry."""
    assert psd.__mccode_role__() == 'unmodelled-component'
    assert psd.__mccode_extra__() == {'mccode_type': 'PSD_monitor'}


def test_the_provenance_names_opaque_and_the_type_it_stood_in_for(psd):
    from niess.provenance import NiessProvenance
    provenance = NiessProvenance.from_instance(one(psd))
    assert provenance.source_type == 'niess.components.opaque.Opaque'
    assert provenance.role == 'unmodelled-component'
    assert provenance.extra['mccode_type'] == 'PSD_monitor'


def test_a_runtime_parameter_is_declared_and_passed_by_name():
    """`Component.to_mccode` already does this; an `Opaque` gets it for free."""
    from mccode_antlr.common import InstrumentParameter
    opening = InstrumentParameter.parse('slit_width/"m" = 0.03')
    slit = Opaque(name='slit', position=vector([0, 0, 1.0], unit='m'),
                  orientation=unrotated(), mccode_type='Slit',
                  mccode_parameters={'xwidth': opening})
    instrument = Instrument(name='test', origin='slit',
                            parts=(Mount(name='part', content=slit),))
    emitted = to_mccode(instrument)
    assert 'slit_width' in [p.name for p in emitted.parameters]
    assert str(emitted.components[0].get_parameter('xwidth').value) == 'slit_width'
    # not `str(InstrumentParameter)`, which is the declaration and re-parses
    # as arithmetic: `slit_width/"m"=0.03` -> `slit_width*1.0/"m"`
    assert emitted.get_parameter('slit_width').value.value == 0.03


def test_the_clauses_it_was_written_with_survive():
    gated = Opaque(name='det', position=vector([0, 0, 1.0], unit='m'),
                   orientation=unrotated(), mccode_type='Monitor_nD',
                   when='flag == 1', group='detectors', extend='flag = 0;',
                   split='17', removable=True)
    instance = one(gated)
    assert str(instance.when) == 'flag==1'
    assert instance.group == 'detectors'
    assert 'flag = 0;' in '\n'.join(str(e) for e in instance.extend)
    # SPLIT and REMOVABLE reach the object even though `Instance.to_file` will not
    # print either of them -- see the note in `Opaque`'s docstring.
    assert instance.split.value == 17
    assert instance.removable is True


def test_it_round_trips_through_json(psd):
    from niess.io.json import from_json, to_json
    assert from_json(to_json(psd)) == psd


def test_from_calibration_takes_the_keys_the_converter_writes():
    built = Opaque.from_calibration({
        'name': 'thing',
        'position': vector([1, 2, 3.0], unit='m'),
        'orientation': unrotated(),
        'mccode_type': 'Progress_bar',
        'mccode_parameters': {'percent': 10},
        'when': 'q > 0',
    })
    assert built.mccode_type == 'Progress_bar'
    assert built.mccode_parameters == {'percent': 10}
    assert built.when == 'q > 0'
    assert built.group is None and built.removable is False
