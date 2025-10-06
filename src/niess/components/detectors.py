from typing import ClassVar, Type
from scipp import Variable
from .component import Base


class Wire(Base):
    at: Variable
    to: Variable
    resistivity: Variable

    __struct_field_types__: ClassVar[dict[str, Type]] = {
        'at': Variable,
        'to': Variable,
        'resistivity': Variable,
    }

    def extreme_path_corners(self, horizontal: Variable, vertical: Variable, unit=None):
        from ..spatial import combine_extremes
        from scipp import concat
        return combine_extremes([concat([self.at, self.to], 'vertices')], horizontal, vertical)

    def __eq__(self, other):
        if not isinstance(other, Wire):
            return False
        return self.at == other.at and self.to == other.to

    def approx(self, other):
        from scipp import allclose
        if not isinstance(other, Wire):
            return False
        return allclose(self.at, other.at) and allclose(self.to, other.to)

    def __post_init__(self):
        from scipp import DType
        if self.at.dtype != DType.vector3:
            raise RuntimeError("Wire starting point, at, must be a scipp.DType('vector3')")
        if self.to.dtype != DType.vector3:
            raise RuntimeError("Wire end point, to, must be a scipp.DType('vector3')")
        if self.to.unit != self.at.unit:
            raise RuntimeError("Wire end points must have the same unit")
        from ..utilities import is_scalar, has_compatible_unit
        if not is_scalar(self.resistivity):
            raise ValueError(f"The provided radius is not a scalar")
        if not has_compatible_unit(self.resistivity, 'Ohm/m'):
            raise ValueError(f"Provided unit {self.resistivity.unit} is not convertible to Ohm/m")

    @property
    def resistance(self) -> Variable:
        from scipp import sqrt, dot
        v = self.to - self.at
        return self.resistivity * sqrt(dot(v, v))

    @property
    def center_of_mass(self) -> Variable:
        return (self.at + self.to)/2

    def charge_position(self, a, b) -> Variable:
        if a+b == 0:
            raise RuntimeError("Sum of a and b must not zero")
        return self._charge_position(a/(a+b), b/(a+b))

    def _charge_position(self, fb, fa) -> Variable:
        if fb < 0 or fb > 1 or fa < 0 or fa > 1:
            raise RuntimeError("Both a and b should have the same sign")
        return fa * self.at + fb * self.to

    def continuous_position(self, fa) -> Variable:
        if fa < 0 or fa > 1:
            raise RuntimeError("Relative distance from at must be between 0 and 1")
        return (1 - fa) * self.at + fa * self.to

    def mcstas_parameters(self):
        from numpy import hstack
        center = (self.at + self.to)/2
        axis = (self.to - self.at)/2
        return hstack((center.value, axis.value))

    def center(self):
        return (self.at + self.to) / 2

    def end(self):
        return (self.to - self.at) / 2


class DiscreteWire(Wire):
    elements: int

    __struct_field_types__: ClassVar[dict[str, Type]] = {
        'elements': int, **Wire.__struct_field_types__
    }

    def __eq__(self, other):
        if not isinstance(other, DiscreteWire):
            return False
        return self.elements == other.elements and super().__eq__(other)

    def approx(self, other):
        from numpy import isclose
        if not isinstance(other, DiscreteWire):
            return False
        return isclose(self.elements, other.elements) and super().approx(other)

    def __post_init__(self):
        if self.elements == 0:
            raise RuntimeError("A discrete detector should have a finite number of elements")
        if self.elements < 0:
            raise RuntimeError("A discrete detector must have a positive number of elements")

    def charge_index(self, a, b) -> int:
        from math import floor
        if a * b < 0:
            raise RuntimeError("Both a and b should have the same sign")
        if a+b == 0:
            raise RuntimeError("Sum of a and b must not be zero")
        # Pick the *bin* index (0,N-1) -- but a/(a+b) is on the interval (0,1)
        n = floor(self.elements * (a / (a + b))) if b else self.elements - 1
        if 0 > n or n > self.elements:
            raise RuntimeError("Error calculating index")
        return n

    def index_position(self, index) -> Variable:
        # take the bin center as its position -- this is (n+1/2)/N along the whole length
        fb = (index + 0.5) / self.elements
        return super()._charge_position(1 - fb, fb)

    def charge_position(self, a, b) -> Variable:
        return self.index_position(self.charge_index(a, b))


class DiscreteTube(DiscreteWire):
    radius: Variable

    __struct_field_types__: ClassVar[dict[str, Type]] = {
        'radius': Variable, **DiscreteWire.__struct_field_types__
    }

    def __post_init__(self):
        from ..utilities import is_scalar, has_compatible_unit
        if not is_scalar(self.radius):
            raise ValueError(f"The provided radius is not a scalar")
        if not has_compatible_unit(self.radius, 'm'):
            raise ValueError(f"The provided 'radius' has unit {self.radius.unit} which is not convertible to m")

    def triangulate(self, unit=None):
        from scipp import vector, sqrt, dot, isclose, cross, arange, concat, flatten
        from scipp.spatial import rotations_from_rotvecs
        if unit is None:
            unit = self.at.unit
        lvec = self.to.to(unit=unit) - self.at.to(unit=unit)
        ll = sqrt(dot(lvec, lvec))
        # *a* vector perpendicular to l
        p = cross(lvec, vector([1., 0, 0]) if isclose(lvec.fields.z, ll) else vector([0, 0, 1.]))
        p = p/sqrt(dot(p, p)) * self.radius.to(unit=unit)

        a = arange(start=0, stop=360, step=30, dim='ring', unit='degree')
        r = rotations_from_rotvecs(a*lvec/ll)

        nvr = len(a)  # the number of vertices per ring
        ring = r * p
        li = self.at.to(unit=unit) + arange(start=0, stop=self.elements+1, dim='length') * lvec / self.elements
        vertices = flatten(li + ring, to='vertices')  # the order in the addition is important for flatten
        # 0, elements*[0,nvr), elements*nvr + 1
        vertices = concat((self.at.to(unit=unit), vertices, self.to.to(unit=unit)), 'vertices')
        # bottom cap
        faces = [[0, i + 1, (i + 1) % nvr + 1] for i in range(nvr)]
        # between rings
        for j in range(self.elements):
          z = 1 + j*nvr
          rf = [[[z + i, z + (i + 1) % nvr, z + (i + 1) % nvr + nvr],
                 [z + i, z + (i + 1) % nvr + nvr, z + i + nvr]] for i in range(nvr)]
          faces.extend([triangle for triangles in rf for triangle in triangles])
        # top cap
        last = len(vertices) - 1
        top = [[last, last - i - 1, last - (i + 1) % nvr -1] for i in range(nvr)]
        faces.extend(top)
        return vertices, faces

    def bounding_box(self, basis: Variable, unit=None):
        from ..spatial import bounding_box
        v, _ = self.triangulate(unit=unit)
        return bounding_box(v, basis)

    def __eq__(self, other):
        if not isinstance(other, DiscreteTube):
            return False
        return self.radius == other.radius and super().__eq__(other)

    def approx(self, other):
        from numpy import isclose
        if not isinstance(other, DiscreteTube):
            return False
        return isclose(self.radius, other.radius) and super().approx(other)


class He3Tube(DiscreteTube):
    pressure: Variable

    __struct_field_types__: ClassVar[dict[str, Type]] = {
        'pressure': Variable, **DiscreteTube.__struct_field_types__
    }

    def __post_init__(self):
        from ..utilities import is_scalar, has_compatible_unit
        if not is_scalar(self.pressure):
            raise ValueError(f"The provided pressure is not a scalar")
        if not has_compatible_unit(self.pressure, 'Pa'):
            raise ValueError(f"The provided 'pressure' has unit {self.pressure.unit} which is not convertible to Pa")

    def __eq__(self, other):
        if not isinstance(other, He3Tube):
            return False
        return self.pressure == other.pressure and super().__eq__(other)

    def approx(self, other):
        from numpy import isclose
        if not isinstance(other, He3Tube):
            return False
        return isclose(self.pressure, other.pressure) and super().approx(other)
