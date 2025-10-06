from scipp import Variable
from .component import Component


class Collimator(Component):
    """A device which limits the horizontal divergence and/or scattering kernel size"""
    width: Variable
    height: Variable
    length: Variable
    blades: int  # number of infinitely thin blades that fit within width


class SollerCollimator(Collimator):
    """Collimator with linear width, height, and length"""
    pass


class RadialCollimator(Collimator):
    """Collimator with angular width, linear height, and radial length"""
    radius: Variable  # the inner radius of the collimator blades

