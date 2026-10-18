"""Turning a rotation into the three angles a McCode instrument line carries.

`ROTATED (x, y, z)` means `R_x(x) R_y(y) R_z(z)` applied on the left, so the conversion
has one job: come back with a triple that rebuilds the rotation it was given. Which triple
is not fixed -- more than one represents the same rotation, and at a singularity a whole
family does -- so every test here asks whether the *rotation* survives the round trip
rather than whether particular angles came out.
"""
import warnings

import numpy as np
import pytest
from scipp import vector
from scipp.spatial import rotations

from niess.spatial import mccode_ordered_angles, mccode_quaternion


def as_matrix(orientation):
    """How a rotation acts on the basis; independent of the quaternion's sign."""
    return np.column_stack([(orientation * vector(value=v, unit='m')).value
                            for v in np.eye(3)])


def roundtrip_error(orientation):
    """How far the rebuilt rotation is from the one the angles came from."""
    rebuilt = mccode_quaternion(*mccode_ordered_angles(orientation))
    return np.abs(as_matrix(orientation) - as_matrix(rebuilt)).max()


def random_rotations(count, seed=20260821):
    raw = np.random.default_rng(seed).normal(size=(count, 4))
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    return rotations(values=raw, dims=['q'])


def test_an_arbitrary_rotation_survives_the_round_trip():
    """The extraction this replaces got 7 in 20000 wrong -- and wrong quietly.

    Its gimbal-lock guard tested `x*y + z*w`, which belongs to the YZX convention, while
    the formulas it guarded were ZYX. So it fired away from the singularity, replacing a
    perfectly ordinary rotation with `pitch = 90, yaw = 0`: not an approximation, a
    different rotation, and no error to notice.
    """
    qs = random_rotations(20000)
    worst = max(roundtrip_error(qs['q', i]) for i in range(qs.sizes['q']))
    assert worst < 1e-12


@pytest.mark.parametrize('pitch', [90.0, -90.0])
@pytest.mark.parametrize('roll,yaw', [(0., 0.), (30., 0.), (0., 45.), (30., 45.),
                                      (123., -67.), (-15., 200.)])
def test_a_rotation_at_gimbal_lock_survives_the_round_trip(roll, pitch, yaw):
    """At y = +-90 the x and z rotations stop being separable.

    Only their sum or difference is determined, so any of a family of triples rebuilds the
    rotation. Picking one is all a caller can ask for; picking none of them -- which is
    what happened here before, including two cases that raised from `asin` overshooting
    its domain -- is not.
    """
    assert roundtrip_error(mccode_quaternion(roll, pitch, yaw)) < 1e-12


@pytest.mark.parametrize('pitch,tolerance', [
    (89.999, 1e-11), (-89.999, 1e-11),          # a thousandth of a degree away: exact
    (89.9999999, 1e-8), (-89.9999999, 1e-8),    # a ten-millionth away: ill-conditioned
])
def test_a_rotation_beside_gimbal_lock_survives_the_round_trip(pitch, tolerance):
    """The singularity is a point, and approaching it must not widen it.

    Precision does fall off as it is approached -- separating x from z means dividing by
    something that vanishes there, so a rotation a ten-millionth of a degree from the pole
    keeps about eight digits rather than fifteen. That is the format's conditioning, not a
    defect in the conversion, so the tolerance follows the distance.
    """
    assert roundtrip_error(mccode_quaternion(123.0, pitch, -67.0)) < tolerance


def test_the_angles_come_back_in_mccode_order():
    """x, y, z -- the order a `ROTATED` line carries them in, not the order applied."""
    assert mccode_ordered_angles(mccode_quaternion(11.0, 22.0, 33.0)) == \
        pytest.approx((11.0, 22.0, 33.0))


def test_the_angles_are_plain_floats():
    """They are formatted straight into instrument text, so they cannot be numpy scalars."""
    assert all(type(a) is float for a in mccode_ordered_angles(mccode_quaternion(1., 2., 3.)))


def test_a_tilted_and_turned_disc_keeps_its_tilt():
    """A disc tilted with the guide and turned half a turn about the beam.

    `DiskChopper` turns a disc about its own z so the beam crosses it where its angles
    say -- `orientation * turn`. McStas turns by x, then the new y, then the new z, so
    that is written as the tilt and the turn as they are. The reversed order wrote
    `(0, 0.56, 180)`: a disc whose beam crossed it at the bottom was tilted the wrong way.
    """
    from scipp.spatial import rotations_from_rotvecs
    tilt = rotations_from_rotvecs(vector(value=[0., -0.56, 0.], unit='deg'))
    flip = rotations_from_rotvecs(vector(value=[0., 0., 180.], unit='deg'))
    assert mccode_ordered_angles(tilt * flip) == pytest.approx((0.0, -0.56, 180.0))


def test_gimbal_lock_is_not_announced_to_the_caller():
    """There is nothing to do about it, so it is not worth a warning.

    scipy says it cannot determine all three angles uniquely at the pole, which is true
    and is a property of the three-angle format rather than of the rotation: every triple
    it might pick rebuilds the same one. `ROTATED (0, 90, 0)` is an ordinary thing to
    write and should not raise an alarm from inside a dependency.
    """
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert mccode_ordered_angles(mccode_quaternion(0.0, 90.0, 0.0)) is not None


def test_something_that_is_not_a_rotation_is_refused():
    with pytest.raises(ValueError, match='quaternion'):
        mccode_ordered_angles(vector(value=[0., 0., 1.], unit='m'))


def mcstas_placement(x, y, z):
    """How McStas places a component turned `ROTATED (x, y, z)`.

    `rot_set_rotation` in mccode-r.c, verbatim. It is the matrix taking a vector into the
    component's frame; `AT` positions use its transpose, which is the orientation.
    """
    cx, sx, cy, sy, cz, sz = (f(np.radians(a)) for a in (x, y, z) for f in (np.cos, np.sin))
    t = np.array([[cy * cz, sx * sy * cz + cx * sz, sx * sz - cx * sy * cz],
                  [-cy * sz, cx * cz - sx * sy * sz, sx * cz + cx * sy * sz],
                  [sy, -sx * cy, cx * cy]])
    return t.T


@pytest.mark.parametrize('angles', [(0., 40., 0.), (30., 0., 40.), (10., 20., 30.),
                                    (-75., 12., 140.)])
def test_the_angles_place_a_component_as_mcstas_does(angles):
    """Both ways: McStas's angles mean `mccode_quaternion`, and the angles extracted
    from an orientation make McStas turn the component to that orientation.

    Only a turn about two or more axes tells the orders apart, and the conversion had
    them reversed: R_z R_y R_x, where McStas is R_x R_y R_z.
    """
    orientation = mccode_quaternion(*angles)
    assert np.allclose(as_matrix(orientation), mcstas_placement(*angles))
    extracted = mccode_ordered_angles(orientation)
    assert np.allclose(mcstas_placement(*extracted), as_matrix(orientation))
