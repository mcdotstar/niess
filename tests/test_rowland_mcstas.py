"""niess's analyzer blades against Monochromator_Rowland's own slab placement."""
from __future__ import annotations

import math

import numpy as np
from pytest import approx


def monochromator_rowland_slabs(source, sink, NH, gap, angle_h):
    """Monochromator_Rowland's INITIALIZE, transcribed: slab centres in its own frame.

    The Rowland circle passes through the source, the origin and the sink in the x-z
    plane; the slabs are spaced around its centre by a_width + a_gap, filling
    2 angle_h, with a_gap = gap / R.
    """
    sx, sz, kx, kz = source[0], source[2], sink[0], sink[2]
    det = sx * kz - sz * kx
    r0, r1 = (sx * sx + sz * sz) / 2, (kx * kx + kz * kz) / 2
    cx, cz = (r0 * kz - r1 * sz) / det, (sx * r1 - kx * r0) / det
    radius = math.hypot(cx - sx, cz - sz)
    coverage = math.radians(2 * angle_h)
    a_gap = gap / radius
    a_width = (coverage - (NH - 1) * a_gap) / NH
    om = math.atan2(-cx, -cz)
    th = om + (np.arange(NH) - 0.5 * (NH - 1)) * (a_width + a_gap)
    return np.stack([cx + radius * np.sin(th), np.zeros(NH), cz + radius * np.cos(th)], axis=1)


def test_mcstas_puts_its_slabs_on_the_blades():
    """With the parameters niess emits, McStas's slabs are niess's blades, to a nanometre.

    The source and sink are where the arm's frames put the sample and the triplet,
    seen from the analyzer -- what the component reads from its `source` and `sink`.
    """
    from scipp import vector
    from scipp.spatial import inv
    from niess.bifrost.bifrost import instrument
    from niess.walk import visits
    from .test_brep import _bifrost_placements
    placed = _bifrost_placements()
    arms = {v.id: v.obj for v in visits(instrument()) if type(v.obj).__name__ == 'Arm'}
    assert len(arms) == 45
    for arm_id, arm in arms.items():
        a_pos, a_rot = placed[f'{arm_id}/analyzer']
        local = lambda key: (inv(a_rot) * (placed[key][0] - a_pos)).to(unit='m').values
        params = arm.analyzer.mcstas_parameters(vector([0., 0., 0.], unit='m'), 's', 'k')
        slabs = monochromator_rowland_slabs(local('primary/sample_origin'),
                                            local(f'{arm_id}/detector'),
                                            params['NH'], params['gap'], params['angle_h'])
        blades, *_ = arm.local_blades()
        assert np.abs(slabs - blades).max() == approx(0.0, abs=1e-9), arm_id


def test_emitted_analyzer_numbers_carry_no_arithmetic_noise(monkeypatch):
    """A different numpy build changing the last bits must not change what is written.

    The frozen McStas text and NeXus structure compare written numbers exactly; CI once
    computed angle_h as 4.000000000002278 where a developer's machine gave
    4.000000000002096. Perturbing the arithmetic by ~1e-14 must leave both untouched.
    """
    import niess.bifrost.arm as arm_module
    import niess.bifrost.rowland as rowland
    from scipp import vector
    from niess.bifrost.bifrost import instrument
    from niess.nexus import to_nexus_structure
    from niess.nexus.bifrost import BIFROST_REGISTRY
    from niess.walk import visits

    def emitted():
        inst = instrument()
        arms = [v.obj for v in visits(inst) if type(v.obj).__name__ == 'Arm']
        origin = vector([0., 0., 0.], unit='m')
        angles = [a.analyzer.mcstas_parameters(origin, 's', 'k')['angle_h'] for a in arms]
        structure = to_nexus_structure(inst, registry=BIFROST_REGISTRY)
        return angles, json.dumps(structure)

    import json
    angles, structure = emitted()
    circle, blades = rowland.three_point_circle, arm_module.Arm.local_blades

    def noisy_circle(*args):
        centre, radius, normal = circle(*args)
        return centre + vector([1e-13, -1e-13, 1e-13], unit=centre.unit), radius * (1 + 3e-14), normal

    def noisy_blades(self):
        centres, normals, *rest = blades(self)
        return (centres * (1 + 3e-14), normals * (1 - 3e-14), *rest)

    monkeypatch.setattr(rowland, 'three_point_circle', noisy_circle)
    monkeypatch.setattr(arm_module.Arm, 'local_blades', noisy_blades)
    assert emitted() == (angles, structure)
