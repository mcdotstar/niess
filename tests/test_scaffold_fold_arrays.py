"""Instrument arrays reach the scaffold's constant folding with every value intact.

`DiscChopper.to_mccode` writes its slit edges into DECLARE as
``double {name}edges[] = {...};`` and points `NXdisk_chopper`'s `slit_edges` at
that name. Converting such a `.instr` back means folding `slit_edges` to the list of
edges -- which mccode-antlr could not do before it learnt C array initializers: the
DECLARE value came back as its first element, an array filled in INITIALIZE came
back as nothing, and a vector-valued symbol was never substituted.

No component registry is needed: the components are in-memory stand-ins whose
SETTING PARAMETERS copy the real ones (`NXdisk_chopper` from mcstas-chopper-lib
v4.2.2, `niess.chopcalc.emit.CHOPPER_LIB_REGISTRY`), with empty bodies.
"""
from textwrap import dedent

import pytest

EDGES = [10.0, 30.0, 100.0, 140.0, 350.0, 370.0]

COMPONENTS = {
    'Arm': """\
        DEFINE COMPONENT Arm
        SETTING PARAMETERS ()
        TRACE
        %{
        %}
        END
        """,
    'NXdisk_chopper': """\
        DEFINE COMPONENT NXdisk_chopper
        SETTING PARAMETERS (vector slit_edges, int n_edges=0, radius=0.35, yheight=0,
                            xwidth=0, nu=0, delay=0, park_angle=0, beam_angle=0,
                            zero_angle=0, jitter=0, int abs_out=0, int verbose=0)
        TRACE
        %{
        %}
        END
        """,
}

# `packedges` is exactly what `Assembler.declare_array` writes; the other arrays cover
# what a hand-written .instr may do instead.
INSTR = dedent("""\
    DEFINE INSTRUMENT scaffold_fold_arrays(pack_speed=14.0, pack_park=0.0)
    DECLARE %{
    double packedges[] = {10.0,30.0,100.0,140.0,350.0,370.0};
    double sized[4] = {-10.0, 10.0};
    double shifted[2];
    double grid[2][3] = {{1, 2}, {3, 4, 5}};
    %}
    INITIALIZE %{
    for (int i = 0; i < 2; i++) shifted[i] = sized[i] + 5;
    grid[1][0] = 30;
    %}
    TRACE
    COMPONENT origin = Arm() AT (0, 0, 0) ABSOLUTE
    COMPONENT pack = NXdisk_chopper(
        slit_edges=packedges, n_edges=6, radius=0.35, nu=pack_speed, park_angle=pack_park,
        beam_angle=90, yheight=0.06, xwidth=0.04
    ) AT (0, 0, 5) RELATIVE origin
    COMPONENT shifted_pack = NXdisk_chopper(
        slit_edges=shifted, n_edges=2, radius=0.35, nu=pack_speed
    ) AT (0, 0, 6) RELATIVE origin
    END
    """)


@pytest.fixture(scope='module')
def arrays():
    """A `.instr` holding instrument arrays, parsed without any component registry."""
    from mccode_antlr.loader import parse_mcstas_instr
    from mccode_antlr.reader.registry import InMemoryRegistry

    registry = InMemoryRegistry('scaffold_fold_arrays')
    for name, source in COMPONENTS.items():
        registry.add_comp(name, dedent(source))
    return parse_mcstas_instr(INSTR, registries=[registry])


@pytest.fixture(scope='module')
def declared(arrays):
    from niess.scaffold.fold import declared_variables
    return declared_variables(arrays)


# --- what `declared_variables` recovers --------------------------------------------

def test_a_declared_array_keeps_every_value(declared):
    """Not just the first: `{10.0, 30.0, ...}` used to fold to `10.0`."""
    assert declared['packedges'].value == EDGES


def test_a_declared_length_zero_fills_the_rest(declared):
    assert declared['sized'].value == [-10.0, 10.0, 0, 0]


def test_an_array_filled_in_initialize_is_recovered(declared):
    assert declared['shifted'].value == [-5.0, 15.0]


def test_a_two_dimensional_array_flattens_row_major(declared):
    """Each brace list is one row, as C lays it out: ``{1, 2, 0}``, then ``{30, 4, 5}``
    after INITIALIZE's ``grid[1][0] = 30``. Writing an element needs the declared
    shape, which only reaches INITIALIZE if the declarators are passed on."""
    assert declared['grid'].value == [1, 2, 0, 30, 4, 5]


# --- what the folder makes of a vector parameter -----------------------------------

@pytest.mark.parametrize('instance, expected', [
    ('pack', EDGES),
    ('shifted_pack', [-5.0, 15.0]),
])
def test_a_vector_parameter_folds_to_its_values(arrays, instance, expected):
    from niess.scaffold.fold import folder
    slit_edges = arrays.get_component(instance).get_parameter('slit_edges').value
    assert folder(arrays)(slit_edges, f'{instance}.slit_edges') == pytest.approx(expected)


def test_the_recipe_reads_the_slit_edges(arrays):
    """`windows` are the edges themselves -- `DiscChopper.__mccode__` writes
    `edge_array_values()` unchanged -- not `range(n_edges)` stand-ins."""
    from niess.scaffold.fold import folder
    from niess.scaffold.recipes import nxdisk_chopper
    _, calibration = nxdisk_chopper(arrays.get_component('pack'), folder(arrays))
    windows = calibration['windows']
    assert windows.unit == 'deg'
    assert windows.values.tolist() == pytest.approx(EDGES)
