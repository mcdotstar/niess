"""One niess object, several McStas components, one NeXus group.

`DiscChopper` with several openings is the worked case: a disc whose openings are neither identical nor
evenly spaced cannot be a single McStas `DiskChopper`, so it becomes one per opening --
and the metadata each one carries is what lets an adapter put the disc back together.
"""
from pathlib import Path


def main(outdir: Path) -> None:
    # --8<-- [start:build]
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from scipp import array, scalar, vector
    from scipp.spatial import rotations_from_rotvecs
    from niess.components import DiscChopper

    disc = DiscChopper.from_calibration({
        'name': 'pack',
        'position': vector([0, 0, 5.0], unit='m'),
        'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
        'radius': scalar(0.35, unit='m'),
        'height': scalar(0.06, unit='m'),
        'frequency': scalar(14.0, unit='Hz'),
        # NXdisk_chopper geometry: where the disc's reference mark sits relative to
        # +y, where the beam crosses relative to that mark, and the angular edges of
        # each opening measured from the mark -- all positive, counter-clockwise
        # facing +z. The last opening straddles the mark, so it closes beyond 360.
        'top_dead_center': scalar(15.0, unit='deg'),
        'beam_position': scalar(90.0, unit='deg'),
        'windows': array(values=[10.0, 30.0, 100.0, 140.0, 350.0, 370.0],
                         dims=['edges'], unit='deg'),
    })

    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    disc.to_mccode(assembler, at='origin', rotate='origin')
    assembler.component('sample', 'Arm', at=((0, 0, 8), 'origin'))
    # --8<-- [end:build]

    # Three McStas components, sharing one speed and one delay
    assert [c.name for c in assembler.instrument.components] == [
        'origin', 'pack_slit_0', 'pack_slit_1', 'pack_slit_2', 'sample',
    ]
    assert sorted(p.name for p in assembler.instrument.parameters) == [
        'packdelay', 'packspeed',
    ]

    # --8<-- [start:tags]
    from niess.provenance import NiessProvenance

    for instance in assembler.instrument.components:
        provenance = NiessProvenance.from_instance(instance)
        if provenance is None or 'disc_group_id' not in provenance.extra:
            continue
        print(f'{instance.name:14s} role={provenance.role:22s} '
              f'group={provenance.extra["disc_group_id"]} '
              f'index={provenance.extra["disc_group_index"]} '
              f'edges={provenance.extra["slit_edges"]}')
    # --8<-- [end:tags]

    # --8<-- [start:result]
    from niess.nexus import find_child, get_attribute, to_nexus_structure

    structure = to_nexus_structure(assembler.instrument, origin='sample')
    instrument = structure['children'][0]['children'][0]

    # named for the disc itself: "_slit_0" is a McStas artefact, not something a
    # reader of the NeXus file should have to know about
    disc_group = find_child(instrument, 'pack')
    assert get_attribute(disc_group, 'NX_class') == 'NXdisk_chopper'
    assert find_child(disc_group, 'slits')['config']['values'] == 3
    assert find_child(disc_group, 'slit_edges')['config']['values'] == [
        10.0, 30.0, 100.0, 140.0, 350.0, 370.0,
    ]
    assert find_child(disc_group, 'top_dead_center')['config']['values'] == 15.0
    assert find_child(disc_group, 'beam_position')['config']['values'] == 90.0

    # ...and the three components it was split across are gone
    for index in range(3):
        assert find_child(instrument, f'pack_slit_{index}') is None
    # --8<-- [end:result]

    # The same tags drive the CAD adapter: niess.brep dispatches on role too, so one
    # role builder there rebuilds the disc as a single solid. (Resolving the builder
    # needs no CAD toolkit; building the geometry would.)
    from niess.brep.registry import NiessBRepRegistry

    brep = NiessBRepRegistry()

    @brep.register_role('disc-opening-primary')
    def whole_disc(provenance, instance, params):
        return f'one solid disc for {provenance.extra["disc_group_id"]}'

    primary = next(c for c in assembler.instrument.components
                   if c.name == 'pack_slit_0')
    assert brep.resolve_builder(primary) is whole_disc


if __name__ == '__main__':
    main(Path('.'))
