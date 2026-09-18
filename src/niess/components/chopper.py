import msgspec
from scipp import Variable
from .component import Component
from mccode_antlr.instr import Instance
from mccode_antlr.assembler import Assembler


def _zero_degrees() -> Variable:
    from scipp import scalar
    return scalar(0.0, unit='deg')


def disc_beam_offset(radius: Variable, height: Variable | None = None,
                     zero_angle: Variable | None = None,
                     beam_angle: Variable | None = None) -> Variable:
    """Spindle to beam crossing, for a disc of this size with the beam at this angle.

    The length is ``radius - height/2``, McStas' rule for centring the beam in a slit's
    radial extent, with ``height`` standing in as ``radius`` when it is unset. The
    direction is ``zero_angle + beam_angle`` counter-clockwise about +z from the local +y
    axis, so the default of zero puts the beam at the top of the disc.

    Shared with the calibration code, which has the opposite problem: it knows where the
    beam runs and has to place the spindle. Having one formula rather than two is the
    point -- the two disagreeing is what put every BIFROST disc on the wrong side of the
    beam in the first place.
    """
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs
    turn = _zero_degrees() if zero_angle is None else zero_angle
    if beam_angle is not None:
        turn = turn + beam_angle
    radial = radius / 2 if height is None else radius - height / 2
    rotation = rotations_from_rotvecs(
        vector(value=[0., 0., turn.to(unit='deg').value], unit='deg'))
    # metres regardless of what the calibration measured the disc in, since this is added
    # to a position and handed to McCode
    return (radial * (rotation * vector([0., 1., 0.]))).to(unit='m')


class Chopper(Component):
    """Any device which periodically opens a path that particles may traverse"""
    velocity: Variable  # angular velocity scalar or vector
    delay: Variable  # the time an opening is on the path, as real instruments are set
    radius: Variable
    windows: Variable
    width: Variable  # the path width
    height: Variable  # the path height


class DiscChopper(Chopper):
    """Ideally infinitely thin material with rotation vector parallel to the path.

    One disc, however many openings it has. McStas' ``DiskChopper`` describes ``nslit``
    *identical, evenly spaced* openings and nothing else, so a disc whose openings are
    neither is emitted as a ``GROUP`` of ``DiskChopper`` instances at the same place, one
    per opening -- the alternative that component's own documentation points at. A disc
    with a single opening is emitted as a single component, exactly as before.

    Geometry follows ``NXdisk_chopper``, so the calibration is the same description a
    NeXus file will carry:

    ``zero_angle``
        Where the disc's reference mark sits, as an angle from the local **+y** axis.
        (``top_dead_center`` in ``NXdisk_chopper``, and accepted under that name too.)
    ``beam_angle``
        Where the beam crosses the disc, as an angle from the reference mark. 180 for a
        disc that hangs above the beam. (``beam_position`` in ``NXdisk_chopper``.)
    ``windows`` (``slit_edges``)
        The angular edges of the openings, **measured from the reference mark**: an even
        number of increasing values, two per opening. Giving ``angle`` instead is
        shorthand for one opening centred on the beam, ``beam_angle`` +- ``angle``/2.

    Every angle is positive counter-clockwise viewed facing **+z**, i.e. looking
    downstream. An opening that straddles the reference mark at zero delay is written
    as a final edge beyond 360 degrees -- ``[350, 370]`` rather than ``[350, 10]`` --
    so the pairs stay ordered and each width is simply the difference.

    ``delay`` is when the *disc's* zero-angle point is on the beam. Each opening is
    reached a fixed angle later, which becomes a fixed time only once the speed is known,
    so that part is left to the generated C.
    """
    # `radius` is the outer dimension of the disc.
    # Where the beam crosses the disc, as two angles about +z, positive counter-clockwise
    # viewed facing +z (looking downstream), measured from the local +y axis. Zero for
    # both means the beam crosses at the top of the disc, which is the arrangement McStas'
    # own DiskChopper assumes, so a disc that takes the defaults emits no extra rotation.
    # A chopper hanging above the beam -- the usual one -- has beam_angle = 180.
    zero_angle: Variable = msgspec.field(default_factory=_zero_degrees)
    """From local +y to the disc's zero mark, which slit angles are measured from."""
    beam_angle: Variable = msgspec.field(default_factory=_zero_degrees)
    """From the zero mark to where the beam crosses the disc."""

    @property
    def speed(self):
        from scipp import dot, vector
        from ..spatial import __is_vector__
        if not __is_vector__(self.velocity):
            return self.velocity.to(unit='Hz')
        # TODO verify the sense of this wrt the McStas definition
        return dot(vector(value=[0, 0, 1.]), self.velocity).to(unit='Hz')

    def beam_offset(self) -> Variable:
        """Spindle to beam crossing, as the emitted ``AT`` needs it.

        Worked out here rather than stored, because the length of this vector is not a
        property of the chopper: it is ``radius - height/2``, McStas' rule for centring
        the beam in a slit's radial extent, with ``height`` standing in as ``radius``
        when it is unset. Keeping it as a field recorded a McCode implementation detail
        as though it were geometry, and went stale the moment ``radius`` or ``height``
        was edited.
        """
        return disc_beam_offset(self.radius, self.height,
                                self.zero_angle, self.beam_angle)

    def __mccode_offset__(self) -> Variable:
        return self.beam_offset()

    def __mccode_orientation__(self) -> Variable:
        """Turn the disc so the beam crosses it where the angles say.

        McStas' ``DiskChopper`` always puts the beam at the *top* of its disc -- its
        ``delta_y = radius - yheight/2`` sets the spindle below the component origin, and
        it measures opening angles as ``atan2(x, y + delta_y)``, which is zero on the
        beam. A real disc has the beam wherever ``zero_angle + beam_angle`` puts it, so
        the whole component turns about its own z by that much to match. The default of
        zero leaves the emitted rotation exactly as it was.
        """
        from scipp import vector
        from scipp.spatial import rotations_from_rotvecs
        turn = (self.zero_angle + self.beam_angle).to(unit='deg')
        return self.orientation * rotations_from_rotvecs(
            vector(value=[0., 0., turn.value], unit='deg'))

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import scalar, array, vector
        name = cal['name']
        position = cal['position']
        orientation = cal['orientation']
        velocity = cal.get('velocity', cal.get('frequency'))
        if velocity is None:
            raise ValueError('velocity (or frequency) cannot be None')
        delay = cal.get('delay', scalar(0.0, unit='s'))
        radius = cal['radius']
        # `top_dead_center` and `beam_position` are the NXdisk_chopper field names, which
        # these started out carrying; accept them without writing back to the caller's
        # dictionary, which calibrations reuse across builds.
        zero_angle = cal.get('zero_angle', cal.get('top_dead_center', _zero_degrees()))
        beam_angle = cal.get('beam_angle', cal.get('beam_position', _zero_degrees()))
        # A single `angle` is one opening centred on the beam. Its edges are still
        # measured from the zero mark, like every other window, so the beam angle is
        # where they are centred -- which is what makes a one-opening disc and a
        # many-opening one the same description.
        #
        # Derived rather than written back: calibrations are reused across builds, and a
        # build that edits the dictionary it was handed changes what the next one reads.
        windows = cal.get('windows')
        if windows is None:
            half = cal['angle'].to(unit='deg') / 2 * array(values=[-1, 1], dims=['edges'])
            windows = beam_angle.to(unit='deg') + half
        width = cal.get('width') # None is actually acceptable
        height = cal.get('height')  # None is acceptable, then slit extends to center
        if 'offset' in cal:
            raise ValueError(
                f"{name}: a disc chopper is placed by where the beam crosses it, not by "
                f"how far that is from the spindle. Say zero_angle and beam_angle -- "
                f"beam_angle=180 deg for a disc hanging above the beam -- and the vector "
                f"follows from them, the radius and the slit height. Ignoring an offset "
                f"that was meant to be used would move the disc off the beam, where it "
                f"absorbs every neutron without saying so."
            )
        return cls(
            name=name,
            position=position,
            orientation=orientation,
            velocity=velocity,
            delay=delay,
            radius=radius,
            windows=windows,
            width=width,
            height=height,
            zero_angle=zero_angle,
            beam_angle=beam_angle,
        )

    def slits(self) -> list[tuple[float, float]]:
        """The ``(opening, closing)`` edge pair of each opening, in degrees from the mark.

        Validates what the pairs have to satisfy to be openings of one disc: an even
        number of strictly increasing edges spanning no more than a revolution. They are
        not required to be positive -- an opening centred on a beam at ``beam_angle = 0``
        straddles the mark, and writing it as ``[-85, 85]`` says so more plainly than
        ``[275, 445]``. ``nexus_slit_edges`` puts them in the order ``NXdisk_chopper``
        asks for, which is where that convention actually applies.
        """
        edges = [float(v) for v in self.windows.to(unit='deg').values]
        if len(edges) < 2 or len(edges) % 2:
            raise ValueError(
                f'{self.name} has {len(edges)} slit edges; an even number of at least '
                'two is required, two per opening'
            )
        if any(b <= a for a, b in zip(edges, edges[1:])):
            raise ValueError(f'{self.name} slit edges must strictly increase: {edges}')
        if edges[-1] - edges[0] > 360.0:
            # Exactly 360 is the limiting case: the last opening closes precisely where
            # the first one opens. Beyond that they would overlap themselves.
            raise ValueError(
                f'{self.name} spans {edges[-1] - edges[0]} degrees; the openings would '
                'overlap themselves'
            )
        return [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]

    def __mccode__(self) -> tuple[str, dict]:
        """The disc's parameters, taking its first opening.

        ``theta_0`` and ``delay`` belong to an opening rather than to the disc, so
        :meth:`to_mccode` overwrites them for each one it emits -- in place, which is why
        they are here rather than appended there: a dict keeps the position of a key it
        already has, and the emitted parameter order is worth keeping stable.
        """
        opening, closing = self.slits()[0]
        params = {
            'theta_0': closing - opening,
            'nslit': 1,
            'radius': self.radius.to(unit='m').value,
            'nu': self.speed_parameter(),
            # Not `phase`: a non-zero one makes DiskChopper ignore `delay` and warn.
            'delay': self.delay_parameter(),
        }
        # Only add width or height if provided:
        if self.width is not None:
            params['xwidth'] = self.width.to(unit='m').value
        if self.height is not None:
            params['yheight'] = self.height.to(unit='m').value
        return 'DiskChopper', params

    def speed_parameter(self) -> str:
        """The run-time knob this disc's rotation speed is set by.

        Named here rather than spelled out at each use: it appears in the emitted
        component's parameters, in the generated C that offsets each opening, and in the
        NXlog a NeXus file links to for the value. Three places is enough for them to
        drift.
        """
        return f'{self.name}speed'

    def delay_parameter(self) -> str:
        """The run-time knob saying when this disc's reference opening is at the beam."""
        return f'{self.name}delay'

    def group_name(self) -> str:
        """The McStas GROUP the emitted openings share, when there is more than one.

        Instance names are unique within an instrument, so deriving the group from this
        disc's name makes it unique too.
        """
        return f'{self.name}_group'

    def _counter_clockwise_turn(self, opening: float, closing: float) -> float:
        """How far counter-clockwise this opening is from the beam, in degrees.

        An opening's centre sits ``centre`` degrees from the mark and the beam sits
        ``beam_angle`` degrees from it, so the angle between them is the difference,
        wrapped into one revolution because a rotating disc reaches the same place every
        turn.

        This is geometry, so it is fixed and direction-free. Which way the disc actually
        travels to close that angle -- and therefore how long it takes -- depends on the
        sign of a run-time parameter, so that part is left to the generated C.
        """
        centre = (opening + closing) / 2
        beam = self.beam_angle.to(unit='deg').value
        return (beam - centre) % 360.0

    def opening_turns(self) -> list[float]:
        """How far counter-clockwise each opening is from the beam, in degrees.

        The disc's timing geometry, in declaration order, without any of the McStas
        machinery that turns it into a per-component ``delay``.
        """
        return [self._counter_clockwise_turn(opening, closing)
                for opening, closing in self.slits()]

    def _slit_delay(
            self, assembler: Assembler, name: str, opening: float, closing: float
    ) -> str:
        """When this opening's centre is at the beam, as a McStas ``delay``.

        Every opening turns with the disc, so they share the one run-time
        ``{name}delay``; each is offset from it by however long the disc takes to bring
        that opening round. The angle is fixed geometry, but the time is not: it depends
        on both the magnitude and the *sign* of ``{name}speed``, and neither is known
        until the simulation runs. A disc that turns clockwise reaches an opening lying
        counter-clockwise of the beam by going the other way round, through the
        explementary angle.

        So the angle is computed here and the rest is left to the generated C, where the
        speed is a real number rather than a name. An opening already at the beam is a
        special case worth taking: it is there at ``{name}delay`` whichever way the disc
        spins, so it needs no variable at all -- which is every disc described by a plain
        ``angle``, since that centres its one opening on the beam.
        """
        turn = self._counter_clockwise_turn(opening, closing)
        if turn == 0:
            return self.delay_parameter()

        speed = self.speed_parameter()
        assembler.declare(f'double {name}_delay;')
        assembler.initialize(
            f'{name}_delay = {self.delay_parameter()} + '
            f'({speed} < 0 ? {360.0 - turn} : {turn}) / (360.0 * fabs({speed}));'
        )
        return f'{name}_delay'

    def _opening_extra(self, index: int, opening: float, closing: float,
                       several: bool) -> dict:
        """What the provenance records about one emitted opening.

        Every disc carries its own geometry, so a NeXus translator can rebuild an
        ``NXdisk_chopper`` from any of them. Only a disc split across several components
        also carries the group tags that say which instances belong together.
        """
        extra = {
            'slit_edges': [opening, closing],
            # NXdisk_chopper's own names, which the NeXus translator writes
            'top_dead_center': self.zero_angle.to(unit='deg').value,
            'beam_position': self.beam_angle.to(unit='deg').value,
            # The disc's own timing, so a translator rebuilding the disc can link it
            # without re-deriving the parameter naming convention.
            'delay_parameter': self.delay_parameter(),
        }
        if several:
            extra['nexus_group_id'] = self.name
            extra['nexus_group_index'] = index
        return extra

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
    ) -> Instance | list[Instance]:
        """Emit one ``DiskChopper`` per opening.

        A single opening emits a single component under the disc's own name, which is
        what a disc chopper has always been. Several emit a ``GROUP`` -- one disc, so a
        neutron passes if it clears *any* opening, where ungrouped each instance would
        absorb whatever missed its own slit and a neutron would have to be inside every
        opening at once to survive.

        Returns the instance, or the list of them, to match.
        """
        from mccode_antlr.common.parameters import InstrumentParameter as InstPar
        from ..mccode import add_niess_metadata, ensure_runtime_line, ensure_runtime_parameter
        from ..spatial import mccode_ordered_angles

        ensure_runtime_line(
            assembler, f'{self.speed_parameter()}/"Hz" = {self.speed.value}')
        ensure_runtime_line(
            assembler,
            f'{self.delay_parameter()}/"s" = {self.delay.to(unit="s").value}'
        )

        position = self.position + self.__mccode_offset__()
        placement = (position.to(unit='m').value, 'ABSOLUTE' if at is None else at)
        rotation = (mccode_ordered_angles(self.__mccode_orientation__()),
                    'ABSOLUTE' if rotate is None else rotate)

        component, shared = self.__mccode__()
        slits = self.slits()
        several = len(slits) > 1

        instances = []
        for index, (opening, closing) in enumerate(slits):
            name = f'{self.name}_slit_{index}' if several else self.name
            parameters = dict(shared)
            # overwritten, not added: see __mccode__ on why the order matters
            parameters['theta_0'] = closing - opening
            parameters['delay'] = self._slit_delay(assembler, name, opening, closing)
            # as Component.to_mccode does: a parameter given as an instrument parameter
            # has to be declared before it can be named
            for key, value in [(k, v) for k, v in parameters.items()
                               if isinstance(v, InstPar)]:
                ensure_runtime_parameter(assembler, value)
                parameters[key] = str(value)

            instance = assembler.component(
                name, component,
                at=placement, rotate=rotation, parameters=parameters,
            )
            if several:
                instance.GROUP(self.group_name())
            if insert_provenance_metadata:
                add_niess_metadata(
                    instance, self,
                    source_name=name,
                    role=('nexus-group-primary' if index == 0 else 'nexus-group-member')
                    if several else self.__mccode_role__(),
                    extra=self._opening_extra(index, opening, closing, several),
                )
            instances.append(instance)
        return instances if several else instances[0]


class FermiChopper(Chopper):
    """Ideally infinitely tall cylinder with a group of curved channels through
    its center, rotation vector parallel to its axis, and perpendicular to the path"""
    # `radius` describes the cylinder dimension
    # `windows` are the edges of the channels, as offsets from the central line
    # `delay` is when the central line is aligned with the path
    curvature: Variable