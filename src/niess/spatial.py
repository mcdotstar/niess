from __future__ import annotations

from scipp import Variable


def __is_vector__(x: Variable):
    from scipp import DType
    return x.dtype == DType.vector3


def is_scipp_vector(v: Variable, name: str):
    from scipp import DType
    if v.dtype != DType.vector3:
        raise RuntimeError(f"The {name} must be a scipp.DType('vector3')")


def __is_quaternion__(x: Variable):
    from scipp import DType
    return x.dtype == DType.rotation3


def vector_to_vector_quaternion(fr: Variable, to: Variable):
    if not __is_vector__(fr) or not __is_vector__(to):
        raise RuntimeError("Two vectors required!")
    from scipp import sqrt, dot, cross
    from scipp.spatial import rotations
    from numpy import concatenate, expand_dims
    # following http://lolengine.net/blog/2013/09/18/beautiful-maths-quaternion-from-vectors
    u = fr / sqrt(dot(fr, fr))
    v = to / sqrt(dot(to, to))
    scalar_part = 0.5 * sqrt(2 + 2 * dot(u, v))
    vector_part = 0.5 * cross(u, v) / scalar_part
    values = concatenate((vector_part.values, expand_dims(scalar_part.values, axis=-1)), axis=-1)
    dims = vector_part.dims

    q = rotations(values=values, dims=dims)
    return q


def combine_triangulations(vts: list[tuple[Variable, list[list[int]]]]):
    from scipp import concat
    from numpy import cumsum, hstack
    if any((v.ndim != 1 for v, t in vts)):
        raise RuntimeError("All vertices expected to be 1-D lists of vectors")
    vdims = [v.dims[0] for v, t in vts]
    if any((d != vdims[0] for d in vdims)):
        raise RuntimeError("All vertex arrays expected to have the same dimension name")
    vdim = vdims[0]

    lens = [len(v) for v, t in vts]
    offset = hstack((0, cumsum(lens)))[:-1]
    faces = [[off + i for i in t] for off, (v, ts) in zip(offset, vts) for t in ts]

    vertices = concat([v for v, t in vts], dim=vdim)

    return vertices, faces


def write_off_file(vertices, faces, filename):
    stream = f"OFF\n{len(vertices)} {len(faces)} 0\n"
    for v in vertices.values:
        s = " ".join([f"{x:3.9f}" for x in v])
        stream += s + "\n"
    for v in faces:
        s = " ".join([f"{x}" for x in v])
        stream += f"{len(v)} {s}\n"
    with open(filename, 'w') as f:
        f.write(stream)


def combine_extremes(vs: list[Variable], horizontal: Variable, vertical: Variable):
    from scipp import concat, dot, sqrt, scalar, isclose, cross
    from numpy import argmax, argmin, hstack, unique
    is_scipp_vector(horizontal, 'horizontal')
    is_scipp_vector(vertical, 'vertical')
    map(lambda p: is_scipp_vector(p, 'x'), vs)
    if any((v.ndim != 1 for v in vs)):
        raise RuntimeError("All vertices expected to be 1-D lists of vectors")
    dim = vs[0].dims[0]
    if any((v.dims[0] != dim for v in vs)):
        raise RuntimeError("All vertex arrays expected to have the same dimension name")
    vs = concat(vs, dim)
    y = horizontal / sqrt(dot(horizontal, horizontal))
    z = vertical / sqrt(dot(vertical, vertical))
    if not isclose(dot(z, y), scalar(0.)):
        z = z - dot(z, y) * y
        z = z / sqrt(dot(z, z))
    x = cross(y, z)
    v_yz = vs - dot(x, vs) * x
    v_yz_pp = dot(v_yz, y + z).values
    v_yz_pm = dot(v_yz, y - z).values
    v_yz_p0 = dot(v_yz, y).values
    v_yz_0p = dot(v_yz, z).values
    max_pp, max_pm, max_p0, max_0p = [argmax(x) for x in (v_yz_pp, v_yz_pm, v_yz_p0, v_yz_0p)]
    min_pp, min_pm, min_p0, min_0p = [argmin(x) for x in (v_yz_pp, v_yz_pm, v_yz_p0, v_yz_0p)]

    idxs = hstack([max_p0, max_pp, max_0p, min_pm, min_p0, min_pp, min_0p, max_pm])  # order is important
    _, unique_index = unique(idxs, return_index=True)
    idxs = idxs[sorted(unique_index)]  # only indexes which are unique, in the same order as provided in idxs

    return vs[idxs]


def perpendicular_directions(direction: Variable):
    from scipp import sqrt, dot, cross, scalar, isclose, abs, vector
    is_scipp_vector(direction, 'direction')

    direction /= sqrt(dot(direction, direction))

    horizontal = vector([1., 0, 0]) if isclose(abs(direction.fields.y), scalar(1.)) else vector([0, -1., 0])
    horizontal -= dot(horizontal, direction) * direction
    horizontal /= sqrt(dot(horizontal, horizontal))

    vertical = cross(horizontal, direction)

    return horizontal, vertical


def bounding_box(points: Variable, basis: Variable):
    """ Find the minimal box with axes along `basis` that contains all `points`

    :param points:
        3-D vector points representing a continuous object in space
    :param basis:
        One or more basis vectors along which to calculate the bounding box.
        The basis _should_ be orthogonal, normal, and span space; but a projected
        basis is allowed (less than 3 basis vectors), normalized vectors will be
        enforced, and orthogonality is not checked.
    :return:
        The (2, len(basis)) limiting corners of the bounding box ordered from
        the minimum corner to the maximum corner; with named axis 'limits'
    """
    from scipp import norm, dot, min, max, concat
    is_scipp_vector(points, 'points')
    is_scipp_vector(basis, 'basis')
    basis = basis / norm(basis)
    if basis.ndim > 1:
        basis = basis.flatten(to='basis')

    projections = dot(points.flatten(to='points'), basis)
    lower = min(projections, dim='points')
    upper = max(projections, dim='points')
    box = concat((lower, upper), dim='limits')
    return box.transpose(['limits', basis.dim]) if basis.ndim > 1 else box


def combine_bounding_boxes(boxes: Variable, limits: str | None = None, basis: str | None = None):
    """Find the box which bounds one or more bounding boxes

    A bounding box can be represented as its minimum and maximum corners.
    This method leverages named `scipp.Variable` axes to identify the corners-axis.
    To allow dimensional flexibility, the box-axes are handled separately with the
    `scipp.Variable` axis representing them identified as the basis dimension.
    Any additional axis or axes are flattened and reduced to find the single
    all-containing bounding box.

    Params
    ------
    boxes:
        A (N, 2, ...) [or any permutation] array of bounding box limits.
    limits:
        The name of the array dimension that identifies the minimum and maximum corner.
        This dimension must be exactly 2-elements long.
        Default = 'limits'
    basis:
        The name of the array dimension that identifies the box basis, (e_1, e_2, ...).
        The length of the array in this dimension is the dimensionality of the space.
        Default = 'basis'
    Returns
    -------
    :
        The (2, N) all-encompassing bounding box, with limit-dimension and
        basis-dimension names matching those in the input bound boxes array
    """
    from scipp import min, max, concat
    limits = limits or 'limits'
    basis = basis or 'basis'
    if limits not in boxes.dims or 2 != boxes.sizes[limits]:
        raise ValueError(f'The boxes must have a `limits` ({limits}) axis of length 2')
    if basis not in boxes.dims:
        raise ValueError(f'The boxes must have a `basis` ({basis}) axis')

    others = [dim for dim in boxes.dims if dim not in (limits, basis)]
    if len(others):
        from uuid import uuid4
        dim = str(uuid4())
        box = boxes.transpose([limits, basis, *others]).flatten(dims=others, to=dim)
        lower = min(box[limits, 0], dim=dim)
        upper = max(box[limits, 1], dim=dim)
        box = concat((lower, upper), dim=limits)
    else:
        box = boxes

    return box.transpose([limits, basis])


def mccode_ordered_angles(orientation: Variable):
    """Determine the McCode ordered Euler angles that represent a quaternion

    In McCode instruments, a rotation is specified as (x, y, z), indicating the
    ordered rotation, R_z(z) R_y(y) R_x(x), which is applied on the left of a vector,
        v_rotated = R_z(z) R_y(y) R_x(x) v

    Each R matrix is the 'standard' rotation matrix with the noted axis constant,
              [1  0      0     ]          [ cos(y) 0 sin(y)]          [cos(z) -sin(z) 0]
        R_x = [0 cos(x) -sin(x)]    R_y = [ 0      1 0     ]    R_z = [sin(z)  cos(z) 0]
              [0 sin(x)  cos(x)]          [-sin(y) 0 cos(y)]          [0       0      1]

    Parameters
    ----------
    orientation: `scipp.Variable`
        A quaternion-valued scalar representing the transformation between two
        orthonormal axes systems.

    Returns
    -------
    : `tuple[float, float, float]`
        The x, y, and z angles needed to represent the same transformation in a McCode
        instrument component instance definition line, e.g., `ROTATED (x, y, z)`.
    """
    if not __is_quaternion__(orientation):
        raise ValueError(f"{orientation=} expected to be a scipp quaternion")
    from math import asin, atan2, pi

    # Follow the suggestions at Wikipedia.com, and the gimbal-lock avoidance
    # from EuclideanSpace.com
    # https://en.wikipedia.org/wiki/Conversion_between_quaternions_and_Euler_angles
    # http://www.euclideanspace.com/maths/geometry/rotations/conversions/quaternionToEuler/

    x, y, z, w = orientation.value
    lock = x * y + z * w
    if lock > 0.4999:
        # gimbal lock with straight-up orientation
        pitch = pi / 2
        roll  = 2 * atan2(x, w)
        yaw = 0
    elif lock < -0.4999:
        # gimbal lock with straight-down orientation (pitch = -90)
        pitch = -pi / 2
        roll = -2 * atan2(x, w)
        yaw = 0
    else:
        roll = atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        pitch = asin(2 * (w * y - x * z))
        yaw = atan2(2 * (w * z + x * y), 1 - 2 * (y *y + z * z))

    return 180 / pi * roll, 180 / pi * pitch, 180 / pi * yaw


def mccode_quaternion(x, y, z):
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs as r
    rx = r(vector([x, 0, 0], unit='deg'))
    ry = r(vector([0, y, 0], unit='deg'))
    rz = r(vector([0, 0, z], unit='deg'))
    q = rz * ry * rx
    return q


def at_relative(relative_position: Variable, relative_orientation: Variable, position: Variable):
    if not __is_vector__(relative_position):
        raise ValueError('The position of the relative coordinate system must be a vector')
    if not __is_quaternion__(relative_orientation):
        raise ValueError('The orientation of the relative coordinate system must be a quaternion')
    if isinstance(position, Variable) and not __is_vector__(position):
        from scipp import vector
        print('Warning, implicit relative z-axis positioning')
        position = position * vector([0, 0, 1.0])

    if not __is_vector__(position):
        raise ValueError('The position in the relative coordinate system must be a vector')
    from numpy import eye
    from scipy.spatial.transform import Rotation
    from scipp.spatial import affine_transform
    a_mat = eye(4)
    a_mat[:3, :3] = Rotation(relative_orientation.value).as_matrix() # rotation part
    a_mat[:3, 3] = relative_position.value  # translation part
    a = affine_transform(value=a_mat, unit=relative_position.unit)
    return (a * position.to(unit=a.unit)).to(unit=position.unit)


def at_relative_dict(relative_dict: dict, position: Variable):
    if 'position' not in relative_dict:
        raise ValueError('The relative dictionary must have a position')
    if 'orientation' not in relative_dict:
        raise ValueError('The relative dictionary must have a orientation')
    return at_relative(relative_dict['position'], relative_dict['orientation'], position)


def rotate_relative(relative_orientation: Variable, orientation: Variable):
    if not __is_quaternion__(relative_orientation):
        raise ValueError('The orientation of the relative coordinate system must be a quaternion')
    if not __is_quaternion__(orientation):
        raise ValueError('The orientation relative to the relative coordinate system must be a quaternion')
    return orientation * relative_orientation