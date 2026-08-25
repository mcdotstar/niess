"""What the CAD export currently produces, so that changing how it is driven is safe.

`tests/test_brep.py` checks that four builders return a shape of roughly the right size.
That is not a net for moving the conversion onto the walk: it would keep passing while
every solid in the instrument moved, or while half of them stopped being emitted at all.

These pin the whole assembly -- how many solids, how much material, and where it is --
for the two instruments. Writing them turned up that the last of those was broken: every solid was
exported at the origin, because mccode_antlr's renderer computed each placement inside a
`try` whose `except Exception: pass` discarded a TypeError raised for every component.
Four builder tests could not see it; each builds one shape and checks its size. Fixed
upstream, and not needed at all by the tree-driven export. They are slow (about ten seconds for BIFROST's primary, which
is real OpenCascade work) and they are worth it exactly once, at the point where the
thing driving the conversion changes.

Numbers rather than a golden file: there are four of them per instrument, and a diff of
four numbers is readable where a diff of 188 breps is not.
"""
import pytest

importorskip = pytest.importorskip


@pytest.fixture(scope='module')
def assembly():
    importorskip('build123d', reason='niess.brep needs the brep extra')

    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.brep.via_instr import instrument_to_assembly

    def build(*parts, name='instrument'):
        assembler = Assembler(name, flavor=Flavor.MCSTAS)
        for part in parts:
            part.to_mccode(assembler)
        return instrument_to_assembly(assembler.instrument)

    return build


def measure(compound) -> dict:
    """How many solids, how much material, and the extent of the whole thing."""
    solids = compound.solids()
    box = compound.bounding_box()
    return {
        'solids': len(solids),
        'volume': sum(solid.volume for solid in solids),
        'min': (box.min.X, box.min.Y, box.min.Z),
        'max': (box.max.X, box.max.Y, box.max.Z),
    }


def test_the_teaching_instrument_exports_what_it_did(assembly):
    from niess.teaching import Primary

    found = measure(assembly(Primary.from_calibration(), name='teaching'))
    assert found['solids'] == 7
    assert found['volume'] == pytest.approx(0.012216, rel=1e-4)


def test_the_bifrost_primary_exports_what_it_did(assembly):
    """188 solids from 158 components: a guide is a shell, not a block."""
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters

    found = measure(assembly(Primary.from_calibration(primary_parameters()),
                             name='bifrost'))
    assert found['solids'] == 188
    assert found['volume'] == pytest.approx(0.493135, rel=1e-4)


def test_the_instrument_is_as_long_as_the_instrument(assembly):
    """It was not, and this is what fixing the placement looks like.

    BIFROST's primary runs 162 m from the moderator to the sample and its export used to
    span 4.4 m, because mccode_antlr computed each placement inside a try whose
    `except Exception: pass` discarded a TypeError raised for every component. Fixed
    upstream; and the tree-driven export never needed the expression evaluated at all.
    """
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters

    found = measure(assembly(Primary.from_calibration(primary_parameters()),
                             name='bifrost'))
    assert found['max'][2] - found['min'][2] == pytest.approx(163.15, rel=1e-2)


def test_both_routes_place_things_in_the_same_places():
    """The tree-driven export and the instrument-driven one agree on where and how big.

    They do not agree on how *much*: an emitted instrument also gets mccode_antlr's
    primitive fallback, which draws a McStas component's own geometry for anything niess
    has no builder for -- 57 solids' worth of windows, monitors and choppers here. The
    tree-driven route draws what niess knows about and nothing else. Closing that gap
    means writing those builders, which is not this change.
    """
    importorskip('build123d', reason='niess.brep needs the brep extra')

    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    from niess.brep.via_instr import instrument_to_assembly
    from niess.instrument import Instrument, Mount
    from niess.brep import to_assembly

    part = Primary.from_calibration(primary_parameters())
    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    part.to_mccode(assembler)

    from_instrument = measure(instrument_to_assembly(assembler.instrument))
    from_tree = measure(to_assembly(Instrument(
        name='bifrost', parts=(Mount(name='primary', content=part),))))

    # along the beam, where placement shows: both now span the instrument's length
    assert from_tree['min'][2] == pytest.approx(from_instrument['min'][2])
    assert from_tree['max'][2] == pytest.approx(from_instrument['max'][2])

    assert from_tree['solids'] == 131
    assert from_instrument['solids'] == 188
    # and what niess draws itself is the same material either way
    assert from_tree['volume'] == pytest.approx(from_instrument['volume'], rel=1e-3)


def test_every_registered_builder_is_reached(assembly):
    """A builder that stops being resolved would not change any number above.

    It would change these: the count of solids per niess class. That is what would
    actually break if dispatch moved and a class stopped matching.
    """
    import collections
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    import niess.brep.builders  # noqa: F401 -- registers the builders
    from niess.brep import BREP_REGISTRY
    from niess.provenance import NiessProvenance

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)

    resolved = collections.Counter()
    for instance in assembler.instrument.components:
        if BREP_REGISTRY.resolve_builder(instance) is not None:
            provenance = NiessProvenance.from_instance(instance)
            resolved[provenance.source_type.rsplit('.', 1)[-1]] += 1

    assert dict(resolved) == {
        'ESSource': 1, 'EllipticGuide': 29, 'StraightGuide': 90,
        'Attenuator': 3, 'Jaw': 3, 'Slit': 2, 'Component': 1,
    }
    # 129 of 158. The rest -- 19 windows, 6 discs, 4 monitors -- resolve nothing,
    # because resolving against an emitted instance matches the niess class exactly
    # rather than walking up to a base. A Filter is a Component and there is a builder
    # registered for Component, but that is not how this lookup works; the object-side
    # one added for the walk does walk the MRO, so moving the conversion would give
    # those 29 the generic marker glyph. Worth deciding deliberately, not discovering.
    assert sum(resolved.values()) == 129


def test_the_tree_route_needs_no_expression_evaluated():
    """Which is why it was never subject to the placement bug.

    A component's position is a scipp Variable on the component. The other route reads
    a placement out of a built instrument, where it is an expression that has to be
    reduced -- and reducing it is what silently failed.
    """
    importorskip('build123d', reason='niess.brep needs the brep extra')

    from niess.instrument import Instrument, Mount
    from niess.brep.assembly import BRepContext, _local_placement
    from niess.teaching import Primary
    from niess.walk import visits

    instrument = Instrument(name='teaching', parts=(
        Mount(name='primary', content=Primary.from_calibration()),))
    context = BRepContext(instrument=instrument)

    placed = {}
    for visit in visits(instrument):
        position, _ = context.place(visit, *_local_placement(visit))
        placed[visit.id] = float(position.to(unit='m').value[2])

    # straight off the objects, no evaluation anywhere
    assert placed['primary/chopper'] == pytest.approx(6.76, abs=0.05)
    assert placed['primary/sample_origin'] > placed['primary/chopper']


def test_a_marker_is_only_for_a_marker():
    """Resolving against an object walks up to the nearest registered base.

    So without a guard, every window and monitor -- none with a builder of its own --
    would resolve the bare-Component axes glyph and a CAD export would grow thirty
    crosses nobody put there. Resolving against an emitted instance matches the class
    exactly and never had the question.
    """
    importorskip('build123d', reason='niess.brep needs the brep extra')

    import niess.brep.builders  # noqa: F401 -- registers the builders
    from niess.brep.builders import build_arm
    from niess.components.component import Component
    from niess.components.filter import Filter
    from niess.brep import Subject

    import scipp as sc
    place = dict(position=sc.vector([0., 0., 0.], unit='m'),
                 orientation=sc.spatial.rotation(value=[0., 0., 0., 1.]))
    window = Filter(name='w', composition=None,
                    temperature=sc.scalar(300.0, unit='K'), **place)
    marker = Component(name='m', **place)

    assert build_arm(Subject(name='w', params={}, obj=window)) is None
    assert build_arm(Subject(name='m', params={}, obj=marker)) is not None
