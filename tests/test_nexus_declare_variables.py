"""DECLARE'd instrument variables must reach constant folding.

Re-homed from ``moreniius/tests/test_declare_variables.py``, where these assertions
fail: ``moreniius`` recovered instrument variables from ``CTargetVisitor.instrument_uservars``,
which is populated from USERVARS blocks (``Instr.user``) and never from DECLARE
blocks (``Instr.declare``), so a component parameter referencing a DECLARE'd
variable silently degraded to a bare variable-name string.
"""
import pytest

INSTR = """DEFINE INSTRUMENT declared_variable_test(dummy=0)
DECLARE %{
double chopper_nu;
double chopper_delay = 0.015;
%}
INITIALIZE %{
chopper_nu = 14.0;
%}
TRACE
COMPONENT origin = Arm() AT (0, 0, 0) ABSOLUTE
COMPONENT sample = Arm() AT (0, 0, 20) RELATIVE origin
COMPONENT ch = DiskChopper(theta_0=170, radius=0.35, nu=chopper_nu, delay=chopper_delay) AT (0, 0, 10) RELATIVE origin
END
"""


@pytest.fixture(scope='module')
def instr():
    from mccode_antlr.loader import parse_mcstas_instr
    return parse_mcstas_instr(INSTR)


@pytest.fixture
def context(instr):
    from niess.nexus.via_instr import NexusContext
    return NexusContext(instr, origin_name='sample')


def test_declared_variables_recovered(context):
    """Both DECLARE'd names are recovered, whichever block gives them a value."""
    assert 'chopper_delay' in context.declared
    assert 'chopper_nu' in context.declared


def test_declare_initializer_folds(context):
    """A variable initialized in its DECLARE statement folds to that literal."""
    from mccode_antlr.common import Expr
    from niess.nexus.via_instr.expression import Literal
    assert context.resolve(Expr.parse('chopper_delay')) == Literal(0.015)


def test_initialize_assignment_folds(context):
    """A DECLARE'd variable assigned in INITIALIZE folds to the assigned value."""
    from mccode_antlr.common import Expr
    from niess.nexus.via_instr.expression import Literal
    assert context.resolve(Expr.parse('chopper_nu')) == Literal(14.0)


def test_uservars_excluded_from_folding():
    """USERVARS are per-particle, so they must not take part in instrument folding."""
    from mccode_antlr.loader import parse_mcstas_instr
    from niess.nexus.via_instr import NexusContext

    with_uservars = INSTR.replace(
        'TRACE\n', 'USERVARS %{\ndouble per_particle_thing;\n%}\nTRACE\n'
    )
    context = NexusContext(parse_mcstas_instr(with_uservars), origin_name='sample')
    assert 'per_particle_thing' not in context.declared
    assert 'chopper_nu' in context.declared


def test_disk_chopper_parameters_are_literals(instr):
    """End to end: the NXdisk_chopper node holds numbers, not variable names."""
    from niess.nexus.via_instr import to_nexus_structure
    from niess.nexus.nodes import find_child

    structure = to_nexus_structure(instr, origin='sample')
    instrument = structure['children'][0]['children'][0]
    chopper = find_child(instrument, 'ch')

    assert find_child(chopper, 'rotation_speed')['config']['values'] == 14.0
    assert find_child(chopper, 'delay')['config']['values'] == 0.015
