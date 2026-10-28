"""Simulated samples for BIFROST, made from McStas' own sample components.

A sample is one or more *processes* -- a McStas sample component and its parameters --
and `sample` puts them on BIFROST's sample table as one exchangeable `Sample`::

    from niess.bifrost.samples import Cylinder, sample, vanadium, powder
    rod = Cylinder(radius=0.0015, height=0.02)
    al2o3 = sample(powder('Al2O3_sapphire.laz', rod, share=0.9),
                   vanadium(rod, share=0.1))

Every neutron reaching the sample is given to exactly one process, chosen at random by
``share``, and its weight is divided by the chance of that choice. A process that can
focus aims at one of two targets, again chosen at random with the weight corrected: the
analyzers, or the elastic (Bragg-peak) monitor in proportion to its share of their solid
angle. So on average every process and every target is counted in full, and the shares
only decide where the statistics go.

The targets are fixed in the lab, while the sample hangs from the frame that
``sample_rotation`` (a3) turns, so they are written as ``detector_tank_angle -
sample_rotation`` (a4 - a3) in the components themselves. Not in INITIALIZE: restage gives
both halves of a split instrument the whole INITIALIZE, and a3 there would make every a3
point a primary simulation of its own.

Data files: a `pathlib.Path` is a file of your own and is written as its absolute path,
so it does not depend on the directory the simulation runs in; a sample script can say
``Path(__file__).parent / 'mine.laz'``. A `str` is a file McStas ships, such as
``'Al2O3_sapphire.laz'``, and is found in McStas' data directory.
"""
from __future__ import annotations

from functools import lru_cache
from math import atan, degrees, sin, radians
from pathlib import Path
from textwrap import dedent
from typing import Any

import msgspec

from ..components import Opaque, Section

#: The motors the sample and the tank turn by, as `niess.bifrost.bifrost.instrument` names them
SAMPLE_ROTATION = 'sample_rotation'
TANK_ANGLE = 'detector_tank_angle'


def datafile(path: Path | str) -> str:
    """A data file as McStas source text, quotes included. See the module docstring."""
    if isinstance(path, Path):
        if not path.is_file():
            raise FileNotFoundError(f'no sample data file {path}')
        return f'"{path.resolve()}"'
    if '/' in path or '\\' in path:
        raise ValueError(f'{path!r} is a path: give it as a pathlib.Path, so it is not '
                         f'read relative to wherever the simulation runs')
    return f'"{path}"'


class Cylinder(msgspec.Struct, frozen=True):
    """A solid (or, with ``thickness``, hollow) vertical cylinder, in metres."""
    radius: float
    height: float
    thickness: float = 0.0

    def mccode(self) -> dict:
        own = {'radius': self.radius, 'yheight': self.height}
        return own | ({'thickness': self.thickness} if self.thickness else {})

    def nexus(self) -> dict:
        own = {'shape': 'cylinder', 'radius': (self.radius, 'm'), 'height': (self.height, 'm')}
        return own | ({'thickness': (self.thickness, 'm')} if self.thickness else {})


class Box(msgspec.Struct, frozen=True):
    """A box, in metres: ``width`` across the beam, ``height``, ``depth`` along it."""
    width: float
    height: float
    depth: float

    def mccode(self) -> dict:
        return {'xwidth': self.width, 'yheight': self.height, 'zdepth': self.depth}

    def nexus(self) -> dict:
        return {'shape': 'box', 'size': ([self.width, self.height, self.depth], 'm')}


class Process(msgspec.Struct, frozen=True):
    """One McStas sample component: what it is, its parameters, its share of the neutrons,
    and whether it takes a focusing target (``focus_aw``, ``focus_ah``, ``target_*``).
    Parameters are McStas source, as `Opaque` takes them; give files through `datafile`."""
    name: str
    mccode_type: str
    parameters: dict[str, Any]
    share: float = 1.0
    focuses: bool = True


class Sample(Section):
    """A simulated sample: the arm choosing each neutron's process and target, then the
    processes. Built by `sample`; emitted as its own ``%include``d section, which brings
    the particle variables its choices need with it."""
    choice: Opaque
    scatterers: tuple[Opaque, ...]

    def __mccode_enter__(self, visit):
        entered = super().__mccode_enter__(visit)
        visit.context.assembler.user_vars(dedent("""
        int sample_switch;
        int detector_switch;
        double event_time_zero;
        """))
        return entered


class Target(msgspec.Struct, frozen=True):
    """A direction about the sample to focus on, in degrees, measured in the tank."""
    angle: float
    width: float
    height: float

    def solid_angle(self) -> float:
        return 2 * radians(self.width) * sin(radians(self.height) / 2)

    def mccode(self) -> dict:
        # The tank turns about the lab by a4 and this frame by a3; see the module docstring.
        # ponytail: ignores the goniometer tilts, so a tilted sample's focus misses the
        # 3-degree-high tank once a tilt nears that; rotate the target by them if it matters.
        offset = f' + {self.angle!r}' if self.angle else ''
        angle = f'DEG2RAD * ({TANK_ANGLE} - {SAMPLE_ROTATION}{offset})'
        return {'focus_aw': self.width, 'focus_ah': self.height,
                'target_x': f'sin({angle})', 'target_y': 0.0, 'target_z': f'cos({angle})'}


@lru_cache(maxsize=1)
def targets(tank_height: float = 3.0) -> tuple[Target, Target]:
    """The analyzers and the elastic monitor, from the tank's calibration.

    The analyzers span the channels plus one spacing (90 degrees for nine channels ten
    apart) and ``tank_height`` degrees; the monitor is the tube's width and length seen
    from the sample.
    """
    from .tank import Tank
    tank = Tank.from_calibration()
    angles = [degrees(a) for a in tank.channel_angles]
    # rounded, so that the emitted instrument (and restage's hash of it) is the same text
    # however the calibration's last bits fall
    analyzers = Target(angle=round((min(angles) + max(angles)) / 2, 6) + 0.0,
                       width=round(max(angles) - min(angles) + degrees(tank.channel_spacing), 6),
                       height=tank_height)
    monitor = tank.monitor
    from scipp import norm
    distance = float(norm(monitor.position).to(unit='m').value)
    radius, length = (float(v.to(unit='m').value) for v in (monitor.radius, monitor.length))
    elastic = Target(angle=round(degrees(tank.monitor_angle), 6),
                     width=round(2 * degrees(atan(radius / distance)), 6),
                     height=round(2 * degrees(atan(length / 2 / distance)), 6))
    return analyzers, elastic


def _here(offset=(0., 0., 0.)) -> dict:
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs
    return dict(position=vector([float(x) for x in offset], unit='m'),
                orientation=rotations_from_rotvecs(vector([0., 0., 0.], unit='deg')))


def sample(*processes: Process, offset=(0., 0., 0.), tank_height: float = 3.0) -> Sample:
    """The processes as one sample; see the module docstring.

    ``offset`` is where the sample is mounted, in metres, from the sample position in the
    frame of the stack it sits on: it turns with ``sample_rotation`` and the goniometers,
    so at zero rotation x is across the beam, y up and z along it. Remounting a sample
    off-centre and measuring again is a new `sample` with another offset. The focusing
    targets keep their directions, which for millimetres is what the real sample sees.
    """
    if len(offset) != 3:
        raise ValueError(f'offset is (x, y, z) in metres, not {offset!r}')
    if not processes:
        raise ValueError('a sample needs at least one process')
    names = [p.name for p in processes]
    if len(set(names)) != len(names):
        raise ValueError(f'process names must differ: {names}')
    total = sum(p.share for p in processes)
    if any(p.share <= 0 for p in processes):
        raise ValueError('every share must be positive')
    shares = [p.share / total for p in processes]
    analyzers, elastic = targets(tank_height)
    monitor = round(elastic.solid_angle() / (elastic.solid_angle() + analyzers.solid_angle()), 9)

    # sample_switch: which process; detector_switch: 1 elastic monitor, 0 analyzers
    edges = [sum(shares[:i + 1]) for i in range(len(shares) - 1)]
    pick = ' : '.join(f'(r < {e!r}) ? {i}' for i, e in enumerate(edges))
    pick = f'{pick} : {len(shares) - 1}' if edges else '0'
    weights = ' : '.join(f'(sample_switch == {i}) ? {s!r}' for i, s in enumerate(shares[:-1]))
    weights = f'{weights} : {shares[-1]!r}' if weights else repr(shares[-1])
    focusing = ' || '.join(f'sample_switch == {i}' for i, p in enumerate(processes) if p.focuses)
    choice = Opaque(name='sample_choice', mccode_type='Arm', **_here(), extend=dedent(f"""
    double r = rand01();
    sample_switch = {pick};
    p /= {weights};
    detector_switch = (rand01() < {monitor!r}) ? 1 : 0;
    if ({focusing or '0'}) p /= detector_switch ? {monitor!r} : (1 - {monitor!r});
    """))

    scatterers = []
    for i, process in enumerate(processes):
        aims = ((f'_{n}', t, f' && detector_switch == {j}')
                for j, (n, t) in enumerate((('analyzers', analyzers), ('monitor', elastic))))
        for suffix, target, when in (aims if process.focuses else (('', None, ''),)):
            parameters = dict(process.parameters) | (target.mccode() if target else {})
            scatterers.append(Opaque(
                name=f'{process.name}{suffix}', mccode_type=process.mccode_type,
                mccode_parameters=parameters, **_here(offset),
                extend='event_time_zero = t;', when=f'sample_switch == {i}{when}'))
    return Sample(choice=choice, scatterers=tuple(scatterers))


# What McStas' sample components can do, as processes. Each passes `**parameters` on as
# they are, for anything a helper does not name.

def vanadium(shape: Cylinder | Box, share: float = 1.0, name: str = 'vanadium', **parameters):
    """Incoherent elastic scattering (`Incoherent`), vanadium's cross-sections by default.
    ``Etrans`` and ``deltaE`` (meV) make it a flat mode instead."""
    return Process(name, 'Incoherent', shape.mccode() | parameters, share)


def powder(reflections: Path | str, shape: Cylinder | Box, share: float = 1.0,
           name: str = 'powder', **parameters):
    """Bragg scattering from a powder (`PowderN`), its reflections from a ``.laz`` file.
    It cannot aim at a target, only limit the vertical spread (``d_phi``, degrees), which
    defaults to the taller of the two targets."""
    d_phi = max(t.height for t in targets())
    own = {'reflections': datafile(reflections), 'd_phi': d_phi}
    return Process(name, 'PowderN', shape.mccode() | own | parameters, share, focuses=False)


def tunneling(shape: Cylinder | Box, E_tun: float, share: float = 1.0,
              name: str = 'tunneling', **parameters):
    """An incoherent scatterer with an elastic line and sharp tunnelling lines at
    +-``E_tun`` meV (`Tunneling_sample`): ``f_tun`` and ``f_QE`` split the scattering, and
    ``gamma`` broadens the quasielastic part."""
    own = {'E_tun': E_tun, 'f_tun': parameters.pop('f_tun', 0.5)}
    return Process(name, 'Tunneling_sample', shape.mccode() | own | parameters, share)


def spinwave(shape: Cylinder, share: float = 1.0, name: str = 'spinwave', **parameters):
    """Magnons on a body-centred orthorhombic (oI) lattice (`SpinWave_BCO`): lattice
    ``a1, a2, a3``, couplings ``j, ja, jb, jc, j_110, j_110_prime``, spin ``S``,
    anisotropy ``D``, field ``B`` and temperature ``T``, among others. Different
    ``j_110`` and ``j_110_prime`` split the modes, as altermagnetic MnF2's are."""
    if not isinstance(shape, Cylinder) or shape.thickness:
        raise ValueError('SpinWave_BCO is a solid cylinder')
    return Process(name, 'SpinWave_BCO', shape.mccode() | parameters, share)


def isotropic_sqw(sqw: Path | str, shape: Cylinder | Box, share: float = 1.0,
                  name: str = 'sqw', **parameters):
    """A powder or liquid S(|Q|, w) from a table (`Isotropic_Sqw`), as coherent scattering;
    pass ``Sqw_inc`` too for an incoherent part. Vertical spread limited as for `powder`."""
    d_phi = max(t.height for t in targets())
    own = {'Sqw_coh': datafile(sqw), 'd_phi': d_phi}
    return Process(name, 'Isotropic_Sqw', shape.mccode() | own | parameters, share,
                   focuses=False)


def crystal_sqw(sqw4: Path | str, shape: Cylinder | Box, share: float = 1.0,
                name: str = 'crystal_sqw', **parameters):
    """A single crystal's S(Q, w) from a 4D ``.sqw4`` table (`Single_crystal_inelastic`),
    used as given: no temperature, absorption or multiple scattering. Give its lattice
    (``ax`` ... ``cz``) and orientation as the component takes them. It cannot focus."""
    own = {'sqw': datafile(sqw4)}
    return Process(name, 'Single_crystal_inelastic', shape.mccode() | own | parameters, share,
                   focuses=False)


def crystal(reflections: Path | str, shape: Cylinder | Box, share: float = 1.0,
            name: str = 'crystal', **parameters):
    """Bragg scattering from a single crystal (`Single_crystal`), its reflections from a
    ``.lau`` file; give its lattice and ``mosaic``. It cannot focus."""
    own = {'reflections': datafile(reflections)}
    return Process(name, 'Single_crystal', shape.mccode() | own | parameters, share,
                   focuses=False)
