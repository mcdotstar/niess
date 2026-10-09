from pytest import approx, importorskip


def _origin():
    import scipp as sc
    return sc.vector([0.0, 0.0, 0.0], unit='m')


def _identity():
    import scipp as sc
    return sc.spatial.rotation(value=[0.0, 0.0, 0.0, 1.0])


def _assembly_child(assembly):
    solids = assembly.solids()
    assert len(solids) == 1
    return solids[0]


def test_to_mccode_adds_niess_metadata():
    import scipp as sc
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.components import StraightGuide
    from niess.provenance import NiessProvenance, read_niess_metadata

    guide = StraightGuide(
        name='g1',
        position=_origin(),
        orientation=_identity(),
        length=sc.scalar(3.0, unit='m'),
        left=1.0,
        right=1.0,
        top=1.0,
        bottom=1.0,
        width=sc.scalar(0.1, unit='m'),
        height=sc.scalar(0.2, unit='m'),
    )

    assembler = Assembler('guide_test', flavor=Flavor.MCSTAS)
    instance = guide.to_mccode(assembler, insert_provenance_metadata=True)
    payload = read_niess_metadata(instance)

    assert payload is not None
    assert payload['source_type'].endswith('StraightGuide')
    assert payload['role'] == 'physical-component'
    # the name is not in the payload since schema 3 -- the block hangs off the instance
    # that carries it, so a second copy could only ever repeat what is already there
    assert 'source_name' not in payload
    assert instance.name == 'g1'
    assert NiessProvenance.from_instance(instance).source_name == 'g1'


def test_a_guide_is_drawn_around_its_own_substrate():
    importorskip('build123d')
    import scipp as sc
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.brep import to_assembly
    from niess.instrument import Instrument, Mount
    from niess.components import StraightGuide
    from niess.provenance import add_niess_metadata

    width, height, substrate = 0.1, 0.2, 0.02

    guide = StraightGuide(
        name='g1',
        position=_origin(),
        orientation=_identity(),
        length=sc.scalar(3.0, unit='m'),
        left=1.0,
        right=1.0,
        top=1.0,
        bottom=1.0,
        width=sc.scalar(width, unit='m'),
        height=sc.scalar(height, unit='m'),
        substrate=sc.scalar(substrate, unit='m'),
    )

    assembly = to_assembly(Instrument(
        name='guide_test', parts=(Mount(name='g1', content=guide),)))

    child = _assembly_child(assembly)
    size = child.bounding_box().size
    assert size.X == approx(width + 2 * substrate)
    assert size.Y == approx(height + 2 * substrate)
    assert size.Z == approx(3.0)


def test_a_slit_is_drawn_at_its_own_opening():
    importorskip('build123d')
    import scipp as sc
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.brep import to_assembly
    from niess.instrument import Instrument, Mount
    from niess.components import Slit

    slit = Slit(
        name='slit1',
        position=_origin(),
        orientation=_identity(),
        width=sc.scalar(0.05, unit='m'),
        height=sc.scalar(0.03, unit='m'),
    )

    assembly = to_assembly(Instrument(
        name='slit_test', parts=(Mount(name='slit1', content=slit),)))

    child = _assembly_child(assembly)
    size = child.bounding_box().size
    assert size.X == approx(0.05)
    assert size.Y == approx(0.03)
    assert size.Z > 0.0


def test_a_filter_is_drawn_at_its_own_size():
    importorskip('build123d')
    import scipp as sc
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.brep import to_assembly
    from niess.instrument import Instrument, Mount
    from niess.components import NCrystalFilter

    filt = NCrystalFilter(
        name='f1',
        position=_origin(),
        orientation=_identity(),
        width=sc.scalar(0.4, unit='m'),
        height=sc.scalar(0.2, unit='m'),
        length=sc.scalar(0.1, unit='m'),
        composition='Al_sg225',
        temperature=sc.scalar(300.0, unit='K'),
    )

    assembly = to_assembly(Instrument(
        name='filter_test', parts=(Mount(name='f1', content=filt),)))

    child = _assembly_child(assembly)
    size = child.bounding_box().size
    assert size.X == approx(0.4)
    assert size.Y == approx(0.2)
    assert size.Z == approx(0.1)


def test_a_frame_relative_to_a_sibling_is_placed_from_it():
    """BIFROST's detector angle starts at its analyzer, not at the arm's origin (the sample).

    Placement only, so no CAD kernel is needed: nothing in the tank that hangs from this
    frame has a shape yet, which is why drawing it never showed the frame in the wrong place.
    """
    import scipp as sc
    from niess.bifrost.bifrost import instrument
    from niess.brep.assembly import BRepContext, _local_placement
    from niess.walk import visits
    inst = instrument()
    context = BRepContext(instrument=inst)
    for visit in visits(inst):
        visit.context = context
        context.place(visit, *_local_placement(visit))
    arm = 'tank/channels[0]/pairs[4]'
    analyzer, _ = context.placements[f'{arm}/analyzer']
    turned, _ = context.placements[f'{arm}/detector_angle']
    assert sc.allclose(turned, analyzer, atol=sc.scalar(1e-9, unit='m'))
    sample, _ = context.placements['primary/sample_origin']
    assert sc.norm(turned - sample).value > 1.0


def _bifrost_placements():
    from niess.bifrost.bifrost import instrument
    from niess.brep.assembly import BRepContext, _local_placement
    from niess.walk import visits
    inst = instrument()
    context = BRepContext(instrument=inst)
    for visit in visits(inst):
        visit.context = context
        context.place(visit, *_local_placement(visit))
    return context.placements


def test_each_analyzer_and_triplet_reflect_their_arcs_final_energy():
    """Bragg's law at every analyzer, from where CAD puts the sample, analyzer and triplet.

    Target-independent: the scattering angle at the analyzer, with PG(002), has to give
    the arc's nominal final energy. A triplet hung from the arm instead of the analyzer,
    or left at the analyzer without its distance, fails this.
    """
    import numpy as np
    placed = _bifrost_placements()
    sample = placed['primary/sample_origin'][0].to(unit='m').values
    nominal = [2.7, 3.2, 3.8, 4.4, 5.0]   # meV, arcs 1-5
    for channel in range(9):
        for arc in range(5):
            arm = f'tank/channels[{channel}]/pairs[{arc}]'
            analyzer = placed[f'{arm}/analyzer'][0].to(unit='m').values
            triplet = placed[f'{arm}/detector'][0].to(unit='m').values
            incoming, outgoing = analyzer - sample, triplet - analyzer
            two_theta = np.arccos(np.dot(incoming, outgoing)
                                  / np.linalg.norm(incoming) / np.linalg.norm(outgoing))
            wavelength = 2 * 3.355 * np.sin(two_theta / 2)
            energy = 81.8042 / wavelength ** 2
            assert energy == approx(nominal[arc], rel=0.01), arm
            # BIFROST's analyzers scatter vertically
            assert abs(outgoing[1]) > 0.5, arm


def test_analyzers_and_triplets_are_drawn_where_they_are_placed():
    importorskip('build123d')
    import numpy as np
    from niess.bifrost.bifrost import instrument
    from niess.brep.assembly import BREP_REGISTRY, Subject, _located, mccode_parameters
    from niess.walk import visits
    placed = _bifrost_placements()
    arm = 'tank/channels[2]/pairs[3]'
    nodes = {v.id: v.obj for v in visits(instrument())}
    for node, solids in ((f'{arm}/analyzer', nodes[f'{arm}/analyzer'].count),
                         (f'{arm}/detector', 3)):
        obj = nodes[node]
        builder = BREP_REGISTRY.resolve_for_object(obj)
        shape = builder(Subject(name=node, obj=obj, params=mccode_parameters(obj)))
        assert len(shape.solids()) == solids, node
        located = _located(shape, *placed[node])
        centre = np.array(tuple(located.bounding_box().center()))
        assert np.allclose(centre, placed[node][0].to(unit='m').values, atol=0.02), node


def test_a_radial_collimator_fans_out_in_front_of_the_sample():
    """On its vertical axis, at its own radii, centred on the beam -- as Radial_col_filter.

    build123d's defaults stood the arc on the beam axis and centred its bounding box on
    the axis, which halved its radii and pointed it sideways.
    """
    importorskip('build123d')
    import numpy as np
    from niess.brep.assembly import BREP_REGISTRY, Subject, mccode_parameters
    from niess.components.filter import RadialFilterCollimator
    from niess.bifrost.bifrost import instrument
    from niess.walk import visits
    obj = next(v.obj for v in visits(instrument()) if isinstance(v.obj, RadialFilterCollimator))
    params = mccode_parameters(obj)
    shape = BREP_REGISTRY.resolve_for_object(obj)(Subject(name='wedge', obj=obj, params=params))
    points = np.array([tuple(p) for p in shape.vertices()])
    radii = np.hypot(points[:, 0], points[:, 2])
    assert radii.min() == approx(min(params['filter_minimum_radius'],
                                     params['collimator_minimum_radius']), abs=1e-6)
    assert radii.max() == approx(max(params['filter_maximum_radius'],
                                     params['collimator_maximum_radius']), abs=1e-6)
    assert points[:, 2].min() > 0                                   # in front, along the beam
    assert np.abs(points[:, 1]).max() == approx(params['yheight'] / 2 + 5e-5, abs=1e-4)
    angles = np.degrees(np.arctan2(points[:, 0], points[:, 2]))
    assert angles.min() == approx(-params['angle_width'] / 2, abs=1e-6)
    assert angles.max() == approx(params['angle_width'] / 2, abs=1e-6)
