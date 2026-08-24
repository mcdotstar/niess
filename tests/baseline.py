"""Frozen McStas output, so the walk rewrite can prove it changed nothing.

Every target in niess is downstream of what ``to_mccode`` emits, so the emission is the
thing to pin before moving it onto a registry-driven walk. Three artefacts are frozen per
instrument, because no one of them is sufficient:

``text``
    The rendered ``.instr``, from ``DEFINE INSTRUMENT`` onward. The leading comment block
    is dropped deliberately: it lists the GitHub registries the reader used and their
    versions, several pinned to ``@main``, so it records upstream drift rather than
    anything niess decided. That header is why the previous attempt at this
    (``tests/test_bifrost.py``'s commented-out block) was abandoned as "extremely
    fragile". From ``DEFINE INSTRUMENT`` on there is no version string left.

``structure``
    A summary built here rather than by ``mccode_antlr``. Two reasons. It survives an
    mccode-antlr upgrade, unlike the raw ``Instr`` JSON -- the stale
    ``bifrost_assembler.json`` this replaces is the evidence. And ``str(instrument)``
    *flattens* the nested ``%include`` sub-instruments into one ``DEFINE INSTRUMENT``,
    so the text alone cannot tell a five-section instrument from a flat one.

``graph``
    The particle-flow edges. ``niess.tof`` and ``niess.chopcalc`` both walk this to work
    out path lengths, so it is a real contract and not merely a view of declaration order.

Re-mint with ``python tests/baseline.py`` after a *deliberate* change, and say in the
commit message why the emission moved.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

DATA = Path(__file__).parent / 'data' / 'baseline'


def _teaching():
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.teaching import Primary

    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    Primary.from_calibration().to_mccode(assembler)
    return assembler.instrument


def _bifrost_primary():
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)
    return assembler.instrument


def _bifrost():
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)
    Tank.from_calibration(tank_parameters()).to_mccode(assembler, 'sample_origin')
    return assembler.instrument


#: Name -> builder. ``bifrost_primary`` is kept alongside the whole instrument because the
#: primary is emitted entirely through the generic ``Component.to_mccode`` path while the
#: tank is where every hand-rolled ``assembler.component`` call lives -- so a failure in
#: one and not the other says immediately which half moved.
INSTRUMENTS = {
    'teaching': _teaching,
    'bifrost_primary': _bifrost_primary,
    'bifrost': _bifrost,
}


def instrument_text(instrument) -> str:
    """The rendered instrument, minus the registry header (see the module docstring)."""
    text = str(instrument)
    marker = 'DEFINE INSTRUMENT'
    start = text.find(marker)
    if start < 0:
        raise ValueError(f'{marker} not found in the rendered instrument')
    return text[start:]


def _raw_c(blocks) -> list[str]:
    return [block.source for block in blocks]


def _reference(ref) -> str:
    """``(vector, target)`` rendered as text; the target is a name or ABSOLUTE."""
    value, relative = ref
    to = 'ABSOLUTE' if relative is None else relative.name
    return f'({", ".join(str(v) for v in value)}) RELATIVE {to}'


def _instance(instance) -> dict:
    return {
        'name': instance.name,
        'type': instance.type.name,
        'at': _reference(instance.at_relative),
        'rotate': _reference(instance.rotate_relative),
        'parameters': {p.name: str(p.value) for p in instance.parameters},
        'when': None if instance.when is None else str(instance.when),
        'split': None if instance.split is None else str(instance.split),
        'group': instance.group,
        'extend': _raw_c(instance.extend),
        'jump': [str(j) for j in instance.jump],
        'removable': instance.removable,
        'cpu': instance.cpu,
        # names only: the provenance payload is JSON whose key order is not a contract,
        # and its content is pinned by tests/test_provenance_coverage.py instead
        'metadata': sorted(m.name for m in instance.metadata),
    }


def instrument_structure(instrument) -> dict:
    """Everything niess decides about the instrument, nesting included."""
    return {
        'name': instrument.name,
        'parameters': [str(p) for p in instrument.parameters],
        'dependency': list(instrument.dependency),
        'user': _raw_c(instrument.user),
        'declare': _raw_c(instrument.declare),
        'initialize': _raw_c(instrument.initialize),
        'save': _raw_c(instrument.save),
        'final': _raw_c(instrument.final),
        'metadata': sorted(m.name for m in instrument.metadata),
        # the text flattens these into one DEFINE INSTRUMENT, so pin them here
        'included': [
            {'name': section.name,
             'components': [c.name for c in section.components],
             'parameters': [str(p) for p in section.parameters],
             'declare': _raw_c(section.declare)}
            for section in instrument.included
        ],
        'components': [_instance(c) for c in instrument.components],
    }


def _graph_data(graph) -> dict:
    """Nodes and edges, sorted so the freeze does not pin iteration order.

    Nodes as well as edges: freezing edges alone loses any node that has none, and the
    tank has one -- the elastic monitor is attached to `upstream`, which is None at the
    top level, so it ends up isolated. The first version of this baseline recorded 199
    nodes for a 200-node graph and said nothing about it.
    """
    return {
        'nodes': sorted(graph.nodes()),
        'edges': sorted([source, target] for source, target in graph.edges()),
    }


def instrument_graph(instrument) -> dict:
    """The particle flow through an emitted instrument."""
    return _graph_data(instrument.build_flow_graph())


def niess_flow_graphs() -> dict:
    """niess's own view of the particle flow, for each instrument it can describe.

    Distinct from the frozen mccode graphs above, and not a duplicate of them: McCode
    describes an instrument as a list, so the only flow it can express is declaration
    order. The BIFROST tank branches -- ten paths leave the sample, nine channels and
    the elastic monitor -- and NeXus needs to say so through each group's `inputs` and
    `outputs`. That is the thing McStas cannot hold, which is the whole reason for
    keeping a niess-side graph.

    All three are frozen. Until the child protocol landed only the tank's could be
    built at all: Section.add_to_graph iterated __struct_fields__ rather than parts(),
    so it reached the `_flat` bool and raised on every section that carries one, which
    is both Primary classes.
    """
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.teaching import Primary as Teaching

    return {
        'teaching': _graph_data(Teaching.from_calibration().to_graph()),
        'bifrost_primary': _graph_data(
            Primary.from_calibration(primary_parameters()).to_graph()),
        'bifrost_tank': _graph_data(
            Tank.from_calibration(tank_parameters()).to_graph()),
    }


def nexus_structures() -> dict:
    """NeXus Structure JSON built from the tree, for each instrument.

    Distinct from tests/data/bifrost_nexus_structure_golden.json.gz, which is a frozen
    historical artefact: it pins what `moreniius` produced for a BIFROST instrument
    captured in August 2026, and its input instrument is frozen alongside it precisely
    so the comparison stays meaningful. This one tracks the live tree.
    """
    from niess.instrument import Instrument, Mount
    from niess.targets.nexus import BIFROST_REGISTRY, to_nexus_structure
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.teaching import Primary as Teaching

    teaching = Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Teaching.from_calibration()),))
    bifrost = Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin'),
    ))
    return {
        'teaching': to_nexus_structure(teaching),
        'bifrost': to_nexus_structure(bifrost, registry=BIFROST_REGISTRY),
    }


def niess_objects() -> dict[str, str]:
    """The niess object model itself, as ``niess.io.json`` serialises it.

    The emission goldens cannot see a calibration change that happens to cancel out, nor
    a struct field being reordered -- and M2 reorders one deliberately. This is what makes
    that visible.
    """
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.io.json import to_json

    return {
        'bifrost_primary': to_json(Primary.from_calibration(primary_parameters())).decode(),
        'bifrost_tank': to_json(Tank.from_calibration(tank_parameters())).decode(),
    }


def _read(path: Path) -> str:
    return gzip.decompress(path.read_bytes()).decode()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(text.encode(), mtime=0))


def text_path(name: str) -> Path:
    return DATA / f'{name}.instr.gz'


def structure_path(name: str) -> Path:
    return DATA / f'{name}.structure.json.gz'


def graph_path(name: str) -> Path:
    return DATA / f'{name}.graph.json.gz'


NIESS_FLOW_GRAPHS = DATA / 'niess_flow.graph.json.gz'
NIESS_OBJECTS = DATA / 'niess_objects.json.gz'
NEXUS_STRUCTURES = DATA / 'nexus.json.gz'


def frozen_text(name: str) -> str:
    return _read(text_path(name))


def frozen_json(path: Path):
    return json.loads(_read(path))


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=False)


def mint() -> None:
    for name, build in INSTRUMENTS.items():
        instrument = build()
        _write(text_path(name), instrument_text(instrument))
        _write(structure_path(name), _dump(instrument_structure(instrument)))
        _write(graph_path(name), _dump(instrument_graph(instrument)))
        print(f'minted {name}')
    _write(NIESS_FLOW_GRAPHS, _dump(niess_flow_graphs()))
    _write(NIESS_OBJECTS, _dump(niess_objects()))
    _write(NEXUS_STRUCTURES, _dump(nexus_structures()))
    print('minted niess object model')


if __name__ == '__main__':
    mint()
