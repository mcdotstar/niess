import shutil

import pytest
import networkx as nx
from typing import Hashable

@pytest.fixture(scope='module')
def bifrost_instrument():
    from niess.bifrost import BIFROST
    import copy
    return copy.deepcopy(BIFROST)


def _root_subgraph(graph: nx.Graph, root: Hashable) -> nx.Graph:
    if root not in graph:
        raise ValueError(f"Root node {root!r} not found in graph.")

    if graph.is_directed():
        nodes = set(nx.descendants(graph, root))
        nodes.add(root)
    else:
        nodes = set(nx.node_connected_component(graph, root))
    return graph.subgraph(nodes).copy()


def test_bifrost(bifrost_instrument):
    from niess.tree import flow_graph
    graph = flow_graph(bifrost_instrument)
    sub_graph = _root_subgraph(graph, 'sample')

    assert sub_graph.size() == 100
    for child in ('monitor', *[f'filter[{i}]' for i in range(9)]):
        assert sub_graph.has_edge('sample', f'tank/{child}')

    from niess.mccode import to_mccode
    instr = to_mccode(bifrost_instrument)

    from mccode_antlr.io.extract import extract_to_directory
    from pathlib import Path
    saveto = Path(__file__).parent / 'testing_bifrost'
    if saveto.is_dir():
        shutil.rmtree(saveto)
    extract_to_directory(instr, saveto)

    from niess.nexus import to_nexus_structure
    from niess.nexus.bifrost import BIFROST_REGISTRY
    structure = to_nexus_structure(bifrost_instrument, registry=BIFROST_REGISTRY)

    from json import dump
    with (saveto / 'structure.json').open('w') as f:
        dump(structure, f)