"""Which component feeds which, when the beam does not run in declaration order.

McCode has no way to say that a beam branches. Its instruments are a list, so the flow
through them is taken to be that list in order -- which is right until something splits
the beam. BIFROST does: after the sample one beam becomes many, and every component past
that point ends up recorded as fed by whichever happened to be declared before it.

`to_nexus_structure(..., graph=...)` takes the real flow instead. The `@inputs` and
`@outputs` attributes are the visible consequence.
"""
import pytest
from mccode_antlr import Flavor
from mccode_antlr.assembler import Assembler
from networkx import DiGraph

from niess.nexus.via_instr import to_nexus_structure


def branching():
    """A beam that splits at the sample, feeding two detectors placed either side."""
    assembler = Assembler('branch', flavor=Flavor.MCSTAS)
    assembler.component('source', 'ESS_butterfly', at=((0, 0, 0), 'ABSOLUTE'),
                        parameters={'Lmin': 0.75, 'Lmax': 10.0})
    assembler.component('sample', 'Arm', at=((0, 0, 10.0), 'source'))
    assembler.component('east', 'TOF_monitor', at=((3.0, 0, 0), 'sample'))
    assembler.component('west', 'TOF_monitor', at=((-3.0, 0, 0), 'sample'))
    flow = DiGraph()
    flow.add_edges_from([('source', 'sample'), ('sample', 'east'), ('sample', 'west')])
    return assembler, flow


def attributes_of(structure, name):
    children = structure['children'][0]['children'][0]['children']
    component = next(c for c in children if c.get('name') == name)
    return {a['name']: a['values'] for a in (component.get('attributes') or [])}


def test_without_a_graph_the_beam_is_taken_to_run_in_declaration_order():
    """Which is what McCode says, and is wrong the moment a beam branches."""
    assembler, _ = branching()
    structure = to_nexus_structure(assembler.instrument, origin='sample')
    assert attributes_of(structure, 'west')['inputs'] == 'east'


def test_a_given_graph_says_what_actually_feeds_what():
    assembler, flow = branching()
    structure = to_nexus_structure(assembler.instrument, origin='sample', graph=flow)
    assert attributes_of(structure, 'west')['inputs'] == 'sample'
    assert attributes_of(structure, 'east')['inputs'] == 'sample'


def test_a_component_feeding_several_records_all_of_them():
    """One name is written as a string, several as a list -- the standard's shape."""
    assembler, flow = branching()
    structure = to_nexus_structure(assembler.instrument, origin='sample', graph=flow)
    outputs = attributes_of(structure, 'sample')['outputs']
    assert sorted(outputs) == ['east', 'west']
    assert attributes_of(structure, 'source')['outputs'] == 'sample'
