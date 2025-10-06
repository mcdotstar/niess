# SPDX-FileCopyrightText: 2025-present Gregory Tucker <gregory.tucker@ess.eu>
#
# SPDX-License-Identifier: MIT
from typing import ClassVar, Type
from .component import Base
from scipp import Variable


class IdealCrystal(Base):
    position: Variable
    tau: Variable

    __struct_field_types__: ClassVar[dict[str, Type]] = {'position': Variable, 'tau': Variable}

    def triangulate(self, unit=None):
        from scipp import sqrt, dot, vector, arange, concat, cross, isclose
        from scipp.spatial import rotations_from_rotvecs
        if unit is None:
            unit = self.position.unit
        lt = sqrt(dot(self.tau, self.tau))
        # *a* vector perpendicular to tau
        p = cross(self.tau, vector([1., 0, 0]) if isclose(self.tau.fields.z, lt) else vector([0, 0, 1.]))
        p = (p/sqrt(dot(p, p)) / lt).to(unit=unit)
        a = arange(start=0, stop=360, step=10, dim='vertices', unit='degree')
        r = rotations_from_rotvecs(a*self.tau/lt)
        vertices = concat((self.position, r*p + self.position), dim='vertices')
        lv = len(r)
        triangles = [[0, i + 1, (i + 1)%lv + 1] for i in range(lv)]

        return vertices, triangles

    def extreme_path_corners(self, horizontal: Variable, vertical: Variable, unit=None):
        if unit is None:
            unit = self.position.unit
        return self.position.to(unit=unit)

    def __eq__(self, other):
        if not isinstance(other, IdealCrystal):
            return False
        return self.position == other.position and self.tau == other.tau

    def approx(self, other):
        from scipp import allclose
        if not isinstance(other, IdealCrystal):
            return False
        return allclose(self.position, other.position) and allclose(self.tau, other.tau)
    
    def __post_init__(self):
        from scipp import DType
        if self.position.dtype != DType.vector3:
            raise RuntimeError("position must be of type scipp.DType('vector3')")
        if self.tau.dtype != DType.vector3:
            raise RuntimeError("tau must be of type scipp.DType('vector3')")

    @property
    def momentum(self) -> Variable:
        from scipp import norm
        return norm(self.tau)

    @property
    def momentum_vector(self) -> Variable:
        return -self.tau

    @property
    def plane_spacing(self) -> Variable:
        from math import pi
        return 2 * pi / self.momentum

    def scattering_angle(self, **kwargs) -> Variable:
        from math import pi, inf
        from scipp import asin, scalar, isinf, isnan, abs, norm
        from ..spatial import __is_vector__
        if len(kwargs) != 1:
            raise RuntimeError("A single keyword argument (k, wavenumber, wavelength) is required")
        k = kwargs.get('k', kwargs.get('wavenumber', 2 * pi / kwargs.get('wavelength', scalar(inf, unit='angstrom'))))
        if __is_vector__(k):
            k = norm(k)
        if k.value == 0 or isinf(k) or isnan(k):
            raise RuntimeError("The provided keyword must produce a finite wavenumber")
        t = self.momentum.to(unit=k.unit)
        if t > 2 * abs(k):
            raise RuntimeError(f"Bragg scattering from |Q|={t:c} planes is not possible for k={k:c}")
        return 2 * asin(t / (2 * k))

    def wavenumber(self, scattering_angle: Variable):
        from scipp import sin
        return self.momentum / (2 * sin(0.5 * scattering_angle.to(unit='radian')))

    def reflectivity(self, *a, **k) -> float:
        return 1.

    def transmission(self, *a, **k) -> float:
        return 1.

    def rtp_parameters(self, sample: Variable, center: Variable, out_of_plane: Variable):
        from scipp import cross, dot, sqrt, atan2
        y = cross(out_of_plane, center - sample)
        y /= sqrt(dot(y, y))
        x = cross(y, out_of_plane)
        x /= sqrt(dot(x, x))

        pc = self.position - center
        rtp_x = dot(pc, x)
        rtp_y = dot(pc, y)
        rtp_angle = atan2(x=dot(self.tau, -y), y=dot(self.tau, x))
        return rtp_x, rtp_y, rtp_angle


class Crystal(IdealCrystal):
    shape: Variable  # lengths: (in-scattering-plane perpendicular to Q, perpendicular to plane, along Q)
    orientation: Variable
    mosaic: Variable

    __struct_field_types__: ClassVar[dict[str, Type]] = {
        **{'shape': Variable, 'orientation': Variable, 'mosaic': Variable},
        **IdealCrystal.__struct_field_types__
    }

    def triangulate(self, unit=None):
        from ..spatial import vector_to_vector_quaternion
        from scipp import vectors, vector
        if unit is None:
            unit = self.position.unit
        r = vector_to_vector_quaternion(vector([0, 0, 1.]), self.tau)
        x, y, z = 0.5 * self.shape.value
        vertices = vectors(unit=self.shape.unit, dims=['vertices'],
                          values=[[-x, -y, -z], [+x, -y, -z], [+x, +y, -z], [-x, +y, -z],
                                  [-x, -y, +z], [+x, -y, +z], [+x, +y, +z], [-x, +y, +z]])
        vertices = r * self.orientation * vertices
        faces = [[0, 2, 1], [2, 0, 3], [1, 2, 6], [1, 6, 5], [0, 1, 5], [0, 5, 4],
                 [3, 0, 4], [3, 4, 7], [2, 3, 7], [2, 7, 6], [4, 5, 6], [4, 6, 7]]
        return vertices.to(unit=unit) + self.position.to(unit=unit), faces

    def bounding_box(self, basis: Variable, unit=None):
        from ..spatial import bounding_box
        v, _ = self.triangulate(unit=unit)
        return bounding_box(v, basis)

    def __eq__(self, other):
        if not isinstance(other, Crystal):
            return False
        return self.shape == other.shape and super().__eq__(other)

    def approx(self, other):
        from scipp import allclose
        if not isinstance(other, Crystal):
            return False
        return allclose(self.shape, other.shape) and super().approx(other)

    def __post_init__(self):
        from scipp import DType
        super().__post_init__()
        if self.shape.dtype != DType.vector3:
            raise RuntimeError("shape must be of type scipp.DType('vector3')")
        if self.orientation.dtype != DType.rotation3:
            raise RuntimeError("orientation must be of type scipp.DType('rotation3')")

    def mcstas_parameters(self):
        from numpy import hstack
        return hstack(self.position.value, self.shape.value)
