"""The two goniometer cradles between BIFROST's sample rotation stage and its sample."""
from typing import Any

from ..components.component import Base
from ..components.motor import Motor


class Goniometer(Base):
    """Two tilts on the sample rotation stage, the sample on top.

    ECDC's chain for the real instrument: the sample depends on ``goniometer_upper``,
    a rotation about x (horizontal, across the beam at zero sample rotation), which
    depends on ``goniometer_lower``, about z (along it), which depends on
    ``sample_rotation``. So both tilts turn with the sample rotation, and the upper one
    with the lower. Each is a frame of its own, one axis apiece, so the order is the
    tree's and not a convention every target has to agree on.

    They are Huber cradles from a triple-axis spectrometer, limited to +-15 degrees, and
    absent when a large magnet is mounted, which zero simulates: they take no room. Both
    tilt about the sample position, as the rotation stage already does. Their sign
    conventions against the real motors are unchecked.
    """
    sample: Any
    lower: Motor
    upper: Motor

    def __niess_children__(self):
        from ..components.frame import Frame
        # named for the axes, since the positioners take the motors' names
        lower = Frame(name='goniometer_lower_axis', rotation=(0, 0, self.lower),
                      extra={'frame': 'goniometer'})
        upper = Frame(name='goniometer_upper_axis', rotation=(self.upper, 0, 0),
                      extra={'frame': 'goniometer'})
        return (('goniometer_lower_axis', lower), ('goniometer_upper_axis', upper),
                ('sample', self.sample))

    def __niess_child_frame__(self, visit, label, default):
        if label == 'goniometer_upper_axis':
            return f'{visit.id}/goniometer_lower_axis'
        if label == 'sample':
            return f'{visit.id}/goniometer_upper_axis'
        return default
