"""One niess object, several McStas components, one NeXus group.

A disc whose openings are neither identical nor evenly spaced cannot be a single McStas
`DiskChopper`, so the McStas conversion emits one per opening. That is a fact about
McStas. Every other target sees the disc.
"""
from pathlib import Path


def main(outdir: Path) -> None:
    # --8<-- [start:build]
    from scipp import array, scalar, vector
    from scipp.spatial import rotations_from_rotvecs

    from niess.components import Component, DiscChopper, Section
    from niess.instrument import Instrument, Mount

    upright = rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg'))

    disc = DiscChopper.from_calibration({
        'name': 'pack',
        'position': vector([0, 0, 5.0], unit='m'),
        'orientation': upright,
        'radius': scalar(0.35, unit='m'),
        'height': scalar(0.06, unit='m'),
        'frequency': scalar(14.0, unit='Hz'),
        # NXdisk_chopper geometry: where the disc's reference mark sits relative to +y,
        # where the beam crosses relative to that mark, and the angular edges of each
        # opening measured from the mark -- all positive, counter-clockwise facing +z.
        # The last opening straddles the mark, so it closes beyond 360.
        'top_dead_center': scalar(15.0, unit='deg'),
        'beam_position': scalar(90.0, unit='deg'),
        'windows': array(values=[10.0, 30.0, 100.0, 140.0, 350.0, 370.0],
                         dims=['edges'], unit='deg'),
    })

    class Chopped(Section):
        origin: Component
        pack: DiscChopper
        sample: Component
        _flat: bool = True

    chopped = Instrument(name='chopped', origin='sample', parts=(
        Mount(name='beamline', content=Chopped(
            origin=Component(name='origin', position=vector([0, 0, 0.0], unit='m'),
                             orientation=upright),
            pack=disc,
            sample=Component(name='sample', position=vector([0, 0, 8.0], unit='m'),
                             orientation=upright),
        )),
    ))
    # --8<-- [end:build]

    # --8<-- [start:mccode]
    from niess.mccode import to_mccode

    instrument = to_mccode(chopped)
    emitted = [c.name for c in instrument.components]
    # --8<-- [end:mccode]

    # three McStas components, sharing one speed and one delay, in one GROUP so that a
    # neutron passes if it clears any opening
    assert emitted == ['origin', 'pack_slit_0', 'pack_slit_1', 'pack_slit_2', 'sample']
    assert {c.group for c in instrument.components if c.name.startswith('pack')} == \
           {'pack_group'}
    assert sorted(p.name for p in instrument.parameters) == ['packdelay', 'packspeed']

    # --8<-- [start:nexus]
    from niess.nexus.nodes import find_child, get_attribute
    from niess.targets.nexus import to_nexus_structure

    structure = to_nexus_structure(chopped)
    instrument_group = structure['children'][0]['children'][0]
    groups = [c.get('name') for c in instrument_group['children']
              if c.get('type') == 'group']
    # --8<-- [end:nexus]

    # one disc, because it never came apart
    assert groups == ['origin', 'pack', 'sample']
    pack = find_child(instrument_group, 'pack')
    assert get_attribute(pack, 'NX_class') == 'NXdisk_chopper'
    assert find_child(pack, 'slits')['config']['values'] == 3
    assert find_child(pack, 'slit_edges')['config']['values'] == [
        10.0, 30.0, 100.0, 140.0, 350.0, 370.0,
    ]
    assert find_child(pack, 'top_dead_center')['config']['values'] == 15.0
    assert find_child(pack, 'beam_position')['config']['values'] == 90.0

    # --8<-- [start:tags]
    # The McStas components still carry tags saying which disc they came from, because
    # someone reading the emitted instrument has to put it back together. Nothing
    # reading the tree needs them.
    from niess.provenance import NiessProvenance

    for instance in instrument.components:
        provenance = NiessProvenance.from_instance(instance)
        if provenance is None or 'disc_group_id' not in provenance.extra:
            continue
        print(f'{instance.name:14s} role={provenance.role:22s} '
              f'group={provenance.extra["disc_group_id"]} '
              f'index={provenance.extra["disc_group_index"]} '
              f'edges={provenance.extra["slit_edges"]}')
    # --8<-- [end:tags]


if __name__ == '__main__':
    main(Path('.'))
