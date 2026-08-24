"""The McStas emission is unchanged.

These are the gate for moving ``to_mccode`` onto a registry-driven walk: the walk is
faithful exactly insofar as these keep passing. See ``tests/baseline.py`` for what is
frozen and why, and re-mint with ``python tests/baseline.py`` only for a deliberate change.
"""
import json

import pytest

from .baseline import (
    INSTRUMENTS,
    NIESS_OBJECTS,
    NIESS_TANK_GRAPH,
    frozen_json,
    frozen_text,
    graph_path,
    instrument_graph,
    instrument_structure,
    instrument_text,
    niess_objects,
    niess_tank_graph,
    structure_path,
)

NAMES = sorted(INSTRUMENTS)


@pytest.fixture(scope='module')
def built():
    """Every instrument, built once -- BIFROST takes a second and three tests want it."""
    return {name: build() for name, build in INSTRUMENTS.items()}


def first_difference(actual: str, expected: str) -> str:
    """Where two renderings diverge, as a message worth reading.

    The BIFROST instrument is 215 kB; a bare assert on it prints a diff nobody can use.
    """
    actual_lines, expected_lines = actual.splitlines(), expected.splitlines()
    for number, (got, want) in enumerate(zip(actual_lines, expected_lines), start=1):
        if got != want:
            return (f'line {number} differs:\n'
                    f'  frozen: {want!r}\n'
                    f'  built:  {got!r}')
    if len(actual_lines) != len(expected_lines):
        longer, label = ((actual_lines, 'built') if len(actual_lines) > len(expected_lines)
                         else (expected_lines, 'frozen'))
        extra = longer[min(len(actual_lines), len(expected_lines)):]
        return (f'{label} has {abs(len(actual_lines) - len(expected_lines))} extra '
                f'line(s), first: {extra[0]!r}')
    return 'no difference'


@pytest.mark.parametrize('name', NAMES)
def test_emitted_text_is_unchanged(built, name):
    expected = frozen_text(name)
    actual = instrument_text(built[name])
    assert actual == expected, first_difference(actual, expected)


@pytest.mark.parametrize('name', NAMES)
def test_structure_is_unchanged(built, name):
    """Catches what the text cannot: it flattens the nested %include sections."""
    expected = frozen_json(structure_path(name))
    actual = instrument_structure(built[name])

    assert [c['name'] for c in actual['components']] == \
           [c['name'] for c in expected['components']], 'component names or order moved'
    for got, want in zip(actual['components'], expected['components']):
        assert got == want, f'component {want["name"]} changed'
    assert [s['name'] for s in actual['included']] == \
           [s['name'] for s in expected['included']], 'the %include sections moved'
    assert actual == expected


@pytest.mark.parametrize('name', NAMES)
def test_flow_graph_is_unchanged(built, name):
    """niess.tof and niess.chopcalc both walk this for path lengths."""
    assert instrument_graph(built[name]) == frozen_json(graph_path(name))


def test_niess_tank_graph_is_unchanged():
    """What the re-derived child protocol has to reproduce."""
    assert niess_tank_graph() == frozen_json(NIESS_TANK_GRAPH)


def test_niess_object_model_is_unchanged():
    """A calibration or field-order change the emission goldens could miss."""
    frozen = frozen_json(NIESS_OBJECTS)
    actual = niess_objects()
    assert sorted(actual) == sorted(frozen)
    for key in sorted(frozen):
        # compare as data: these are 100+ kB of JSON, and a text diff is unreadable
        assert json.loads(actual[key]) == json.loads(frozen[key]), f'{key} changed'


def test_the_baseline_describes_the_instruments_we_think_it_does(built):
    """A golden minted from a broken build would pass every test above."""
    assert len(built['teaching'].components) == 7
    assert len(built['bifrost_primary'].components) == 158
    assert len(built['bifrost'].components) == 358
    assert [s.name for s in built['bifrost'].included] == [
        'bifrost_compressor', 'bifrost_curved', 'bifrost_expanding',
        'bifrost_straight', 'bifrost_closing',
    ]


def test_a_moved_component_fails_the_gate():
    """The gate has teeth.

    Without this, a comparison that silently comodified -- normalising away the very
    thing it is meant to catch -- would look exactly like a passing suite.
    """
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from scipp import vector
    from niess.teaching import Primary, teaching_parameters

    parameters = teaching_parameters()
    parameters['chopper']['position'] = parameters['chopper']['position'] + vector(
        [0, 0, 0.001], unit='m'
    )

    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    Primary.from_calibration(parameters).to_mccode(assembler)

    moved = instrument_text(assembler.instrument)
    assert moved != frozen_text('teaching'), 'a 1 mm shift left the emission unchanged'
    assert instrument_structure(assembler.instrument) != frozen_json(
        structure_path('teaching')
    )


def test_a_flattened_section_fails_the_gate(monkeypatch):
    """Why the structure is frozen separately from the text.

    ``str(instrument)`` renders every nested ``%include`` section inline under one
    ``DEFINE INSTRUMENT``, so un-nesting a section changes the instrument's shape while
    leaving the rendered text **byte-identical**. The walk decides nesting, so this is a
    live hazard rather than a theoretical one.
    """
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.teaching import Primary, teaching_parameters
    from niess.teaching.primary import Guides

    monkeypatch.setattr(Guides, '_flat', True, raising=False)

    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    Primary.from_calibration(teaching_parameters()).to_mccode(assembler)

    assert assembler.instrument.included == (), 'the section did not flatten'
    assert instrument_text(assembler.instrument) == frozen_text('teaching'), \
        'the text was expected to be blind to this; if it is not, say so here'
    assert instrument_structure(assembler.instrument) != frozen_json(
        structure_path('teaching')
    ), 'the structure freeze did not catch a flattened section'
