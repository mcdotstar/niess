# SPDX-FileCopyrightText: 2025-present Gregory Tucker <gregory.tucker@ess.eu>
#
# SPDX-License-Identifier: MIT


def test_ideal_crystal():
    from niess.components import IdealCrystal
    from scipp import scalar, array, vector, dot, norm, isclose

    pos = vector([0, 0, 0.], unit='m')
    tau = vector([0, 0, 1.], unit='1/m')

    crystal = IdealCrystal(pos, tau)

    # without any extent, the triangulated ideal crystal is a circle in the plane
    # perpendicular to tau, centered at pos
    vertices, triangle = crystal.triangulate()
    assert all(dot(v, tau) == scalar(0.) for v in vertices)
    assert isclose(norm(vertices.sum(dim='vertices')), scalar(0., unit='m'))

    assert isclose(crystal.momentum, scalar(1., unit='1/m'))

    x = crystal.scattering_angle(wavenumber=tau)
    assert isclose(x, scalar(60.0, unit='deg').to(unit=x.unit))


def box_edge_check(vs, x, y, z):
    from scipp import scalar, norm, isclose
    assert isclose(norm(vs['vertices', 1] - vs['vertices', 0]), scalar(x, unit='m'))
    assert isclose(norm(vs['vertices', 3] - vs['vertices', 2]), scalar(x, unit='m'))
    assert isclose(norm(vs['vertices', 5] - vs['vertices', 4]), scalar(x, unit='m'))
    assert isclose(norm(vs['vertices', 6] - vs['vertices', 7]), scalar(x, unit='m'))

    assert isclose(norm(vs['vertices', 2] - vs['vertices', 1]), scalar(y, unit='m'))
    assert isclose(norm(vs['vertices', 3] - vs['vertices', 0]), scalar(y, unit='m'))
    assert isclose(norm(vs['vertices', 6] - vs['vertices', 5]), scalar(y, unit='m'))
    assert isclose(norm(vs['vertices', 7] - vs['vertices', 4]), scalar(y, unit='m'))

    assert isclose(norm(vs['vertices', 4] - vs['vertices', 0]), scalar(z, unit='m'))
    assert isclose(norm(vs['vertices', 5] - vs['vertices', 1]), scalar(z, unit='m'))
    assert isclose(norm(vs['vertices', 6] - vs['vertices', 2]), scalar(z, unit='m'))
    assert isclose(norm(vs['vertices', 7] - vs['vertices', 3]), scalar(z, unit='m'))


def extrema_check(crystal, basis: list, extents: list):
    from scipp import concat, isclose
    box = crystal.bounding_box(basis=concat(basis, dim='basis'))
    lengths = box['limits', 1] - box['limits', 0]
    for index, extent in enumerate(extents):
        if extent is not None:
            assert isclose(lengths['basis', index], extent)


def test_crystal():
    from itertools import permutations
    from niess.components import Crystal
    from scipp import scalar, vector
    from scipp.spatial import rotations_from_rotvecs

    x, y, z = 1., 2., 0.01
    pos = vector([0, 0, 0.], unit='m')
    tau = vector([0, 0, 1.], unit='1/m')
    shape = vector([x, y, z], unit='m')
    orient = rotations_from_rotvecs(vector([0, 0, 0.], unit='deg'))
    mosaic = scalar(10., unit='arcminutes')

    crystal = Crystal(pos, tau, shape, orient, mosaic)

    vs, triangles = crystal.triangulate()
    expected = [[-x/2, -y/2, -z/2], [x/2, -y/2, -z/2], [x/2, y/2, -z/2], [-x/2, y/2, -z/2],
                [-x/2, -y/2, z/2], [x/2, -y/2, z/2], [x/2, y/2, z/2], [-x/2, y/2, z/2],]
    for index, v in enumerate(expected):
        assert all(a == b for a, b in zip(v, vs['vertices', index].values))
    box_edge_check(vs, x, y, z)

    v = [vector(vv, unit='m') for vv in ([1, 0, 0.], [0, 1, 0.], [0, 0, 1.])]
    s = [scalar(xx, unit='m') for xx in (x, y, z)]
    for p in permutations(range(3), 3):
        extrema_check(crystal, [v[i] for i in p], [s[i] for i in p])


def test_rotated_crystal():
    from itertools import permutations
    from niess.components import Crystal
    from scipp import scalar, vector, cos, sin
    from scipp.spatial import rotations_from_rotvecs

    x, y, z, angle = 1., 2., 0.01, 25.0
    pos = vector([0, 0, 0.], unit='m')
    tau = vector([0, 0, 1.], unit='1/m')
    shape = vector([x, y, z], unit='m')
    orient = rotations_from_rotvecs(vector([0, angle, 0.], unit='deg'))
    mosaic = scalar(10., unit='arcminutes')

    crystal = Crystal(pos, tau, shape, orient, mosaic)

    vs, triangles = crystal.triangulate()
    box_edge_check(vs, x, y, z)

    c, s = [fn(scalar(angle, unit='deg')) for fn in (cos, sin)]
    xz = scalar(x, unit='m') * c + scalar(z, unit='m') * s
    zx = scalar(z, unit='m') * c + scalar(x, unit='m') * s

    v = [vector(vv, unit='m') for vv in ([1, 0, 0.], [0, 1, 0.], [0, 0, 1.])]
    s = xz, scalar(y, unit='m'), zx
    for p in permutations(range(3), 3):
        extrema_check(crystal, [v[i] for i in p], [s[i] for i in p])


