from dataclasses import dataclass
from scipp import Variable
from .component import Component


@dataclass
class Collimator(Component):
    """A device which limits the horizontal divergence and/or scattering kernel size"""
    width: Variable
    height: Variable
    length: Variable
    blades: int  # number of infinitely thin blades that fit within width


@dataclass
class SollerCollimator(Collimator):
    """Collimator with linear width, height, and length"""
    pass


@dataclass
class RadialCollimator(Collimator):
    """Collimator with angular width, linear height, and radial length"""
    radius: Variable  # the inner radius of the collimator blades

