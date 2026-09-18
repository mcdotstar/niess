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


def instrument_graph(instrument) -> list[list[str]]:
    """Particle-flow edges, sorted so the freeze does not pin iteration order."""
    graph = instrument.build_flow_graph()
    return sorted([source, target] for source, target in graph.edges())


def niess_tank_graph() -> list[list[str]]:
    """``Tank.add_to_graph``'s own view of the secondary spectrometer.

    Frozen because the walk rewrite deletes the six hand-written ``add_to_graph``
    overrides and re-derives them from one child protocol; this is what the derived
    graph has to reproduce.

    Only the tank. ``Section.to_graph`` raises ``AttributeError`` on any section
    carrying a ``_flat`` field -- it iterates ``__struct_fields__`` rather than
    ``parts()``, so it reaches the bool -- which means the primary's niess-side graph
    has never been built. Fixing that is part of the rewrite, not of this baseline.
    """
    from networkx import DiGraph
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters

    graph = DiGraph()
    Tank.from_calibration(tank_parameters()).add_to_graph(None, 'tank', graph)
    return sorted([source, target] for source, target in graph.edges())


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


NIESS_TANK_GRAPH = DATA / 'niess_tank.graph.json.gz'
NIESS_OBJECTS = DATA / 'niess_objects.json.gz'


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
    _write(NIESS_TANK_GRAPH, _dump(niess_tank_graph()))
    _write(NIESS_OBJECTS, _dump(niess_objects()))
    print('minted niess object model')


if __name__ == '__main__':
    mint()
