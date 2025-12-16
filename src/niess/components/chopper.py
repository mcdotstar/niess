from scipp import Variable
from .component import Component
from mccode_antlr.instr import Instance
from mccode_antlr.assembler import Assembler


class Chopper(Component):
    """Any device which periodically opens a path that particles may traverse"""
    velocity: Variable  # angular velocity scalar or vector
    phase: Variable
    radius: Variable
    windows: Variable
    width: Variable  # the path width
    height: Variable  # the path height


class DiscChopper(Chopper):
    """Ideally infinitely thin material with rotation vector parallel to the path"""
    # `radius` is the outer dimension of the disc.
    # `windows` are ordered angular edges of the openings in the disc
    # `phase` is the time=0 angular orientation of the disc
    offset: Variable # the position of the path relative to the disc center

    @property
    def speed(self):
        from scipp import dot, vector
        from ..spatial import __is_vector__
        if not __is_vector__(self.velocity):
            return self.velocity.to(unit='Hz')
        # TODO verify the sense of this wrt the McStas definition
        return dot(vector(value=[0, 0, 1.]), self.velocity).to(unit='Hz')

    def chopper_lib_parameters(self):
        """Useful for specifying elements of a vector used by chopper-lib"""
        from scipp import max, min, norm
        speed_name = f'{self.name}speed'
        phase_name = f'{self.name}phase'
        if self.windows.size != 2:
            raise ValueError("chopper-lib expects only one window")
        angle = (max(self.windows) - min(self.windows)).to(unit='deg').value
        distance = norm(self.position).to(unit='m').value
        return '{' + f'{speed_name}, {phase_name}, {angle}, {distance}' + '}'

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import scalar, array, vector
        name = cal['name']
        position = cal['position']
        orientation = cal['orientation']
        velocity = cal.get('velocity', cal.get('frequency'))
        if velocity is None:
            raise ValueError('velocity (or frequency) cannot be None')
        phase = cal.get('phase', scalar(0.0, unit='deg'))
        radius = cal['radius']
        if 'windows' not in cal:
            cal['windows'] = cal['angle'].to(unit='deg') / 2 * array(values=[-1, 1], dims=['edges'])
        windows = cal['windows']
        width = cal.get('width') # None is actually acceptable
        height = cal.get('height')  # None is acceptable, then slit extends to center
        offset = cal.get('offset', vector([0, 0, 0], unit='m'))
        return cls(
            name=name,
            position=position,
            orientation=orientation,
            velocity=velocity,
            phase=phase,
            radius=radius,
            windows=windows,
            width=width,
            height=height,
            offset=offset
        )


    def __mccode__(self) -> tuple[str, dict]:
        from scipp import max, min
        if self.windows.size != 2:
            # The McStas way of handling multiple windows is one of two options:
            #   1. if they are equally spaced and all the same size, use 'nslit'
            #   2. otherwise use a group of choppers all at the same position but
            #      rotated relative to one another by their slit difference. One per.
            raise ValueError("Currently only one window supported. Investigate using a group here")
        params = {
            'theta_0': (max(self.windows) - min(self.windows)).to(unit='deg').value,
            'nslit': 1,
            'radius': self.radius.to(unit='m').value,
            'nu': f'{self.name}speed',
            'phase': f'{self.name}phase',
        }
        # Only add width of height if provided:
        if self.width is not None:
            params['xwidth'] = self.width.to(unit='m').value
        if self.height is not None:
            params['yheight'] = self.height.to(unit='m').value
        return 'DiskChopper', params

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
    ):
        from ..mccode import ensure_runtime_line as ensure
        ensure(assembler, f'{self.name}speed/"Hz" = {self.speed.value}')
        ensure(assembler, f'{self.name}phase/"degree" = {self.phase.to(unit="deg").value}')
        # the offset is handled by super's to_mccode -- no problems.
        return super().to_mccode(assembler, at, rotate)


class FermiChopper(Chopper):
    """Ideally infinitely tall cylinder with a group of curved channels through
    its center, rotation vector parallel to its axis, and perpendicular to the path"""
    # `radius` describes the cylinder dimension
    # `windows` are the edges of the channels, as offsets from the central line
    # `phase` is the t=0 angular orientation of the central line wrt the path
    curvature: Variable