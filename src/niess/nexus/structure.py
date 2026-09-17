"""ESS NeXus Structure JSON, from the tree.

A component's position and orientation are on the component; a frame is a declared node,
so a `depends_on` chain is the chain of frames a thing hangs from; and a detector's arc
and triplet are `visit.ancestor(...).index`. There used to be a route that recovered all
of that from an emitted instrument, in a thousand more lines. It is gone.

Translators are registered per niess class, or written on the class as ``__nexus_leaf__``
and friends -- both work, and which reads better depends on the target. NeXus is mostly a
table of per-type mappings, so registration suits it; McStas has scaffolding to place, so
methods suit that.

Instrument-specific translators are not here: they live in registries of their own, such
as `niess.nexus.bifrost.BIFROST_REGISTRY`, and are selected by passing ``registry=``.
Importing this module must not give another instrument's detectors BIFROST's numbering.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..walk import SKIP, Context, Visit, walk
from .nodes import (SAME_PLACE, add_child, attribute, dataset, group, node_name,
                    resolve_same_place)
from .registry import NEXUS_REGISTRY, NiessNexusRegistry


INSTRUMENT_PATH = '/entry/instrument'

DEFAULT_NXLOG_ROOT = '/entry/parameters'

DEFAULT_STREAM_TOPIC = 'motors'

@dataclass
class NexusContext(Context):
    from mccode_antlr.common import InstrumentParameter

    """The instrument group being filled, and where things have been put in it."""
    nxlog_root: str = DEFAULT_NXLOG_ROOT
    instrument_group: dict = None
    #: NeXus path emitted at each visit, so a depends_on can name it.
    paths: dict = field(default_factory=dict)

    _flow: Any = None
    #: Emitted nodes awaiting their flow datasets, which cannot be written until
    #: every name is known -- a component's successors are emitted after it.
    pending: list = field(default_factory=list)
    #: Emitted name by tree path, so the flow graph's nodes can be named in the file.
    emitted_names: dict = field(default_factory=dict)

    #: Where a driven axis's numbers come from. See :mod:`niess.nexus.bindings`.
    streams: Any = None
    #: Names already used directly under NXinstrument, so a positioner placed beside
    #: one component cannot silently overwrite one placed beside another.
    placed: set = field(default_factory=set)

    def __post_init__(self):
        if self.streams is None:
            from .bindings import SIMULATED
            self.streams = SIMULATED
        if self.instrument_group is None:
            self.instrument_group = group(
                'instrument', nx_class='NXinstrument',
                children=[dataset('name', self.instrument.name),
                          self.neutron_production()])

    def neutron_production(self) -> dict:
        """Where the pulse reference times are recorded.

        Without them a top-dead-centre time cannot be used: a TDC timestamp is only
        meaningful against the pulse it is measured from, and every other timestamp in
        the file -- detector events, motor readbacks, chopper crossings -- has to share
        the same reference or none of them can be compared.

        So one sample per pulse, of something that looks like proton intensity on
        target, timestamped with the reference time itself. `current_log` rather than a
        bare `NXlog`: `NXsource` allows only one of those, while `GROUPNAME_log` --
        NeXus' own "logged values of GROUPNAME" -- admits any number of distinctly named
        logs, so a second per-pulse quantity can join later without displacing this one.

        Under `NXinstrument`, which is the only place `NXsource` is allowed; a group of
        this class directly under `NXentry` does not validate.
        """
        from .streams import f144_log
        source, topic = self.pulse_source_topic()
        return group('neutron_prod_info', nx_class='NXsource', children=[
            dataset('name', 'ESS'),
            dataset('probe', 'neutron'),
            f144_log('current_log', source, topic, 'uA', 'double'),
            # NXsource extends NXcomponent, so it is placed like one -- at the origin,
            # since the accelerator is not somewhere the instrument's frames reach.
            dataset('depends_on', '.'),
        ])

    def pulse_source_topic(self) -> tuple[str, str]:
        """Where the per-pulse reference sample is published."""
        binder = self.streams
        return (getattr(binder, 'pulse_source', None) or 'pulse',
                getattr(binder, 'chopper_topic', None) or 'choppers')

    def linked_log(self, name: str, parameter: str,
                   attrs: dict | None = None) -> dict:
        """A value a run sets, as an NXlog whose datasets link to an existing one.

        A chopper's speed is not a number an instrument has; it is a knob, and what the
        file should say is where to read it. `niess.nexus` decides this by folding a
        McCode expression and seeing whether an instrument parameter survives. Here the
        component names the knob it declared.

        This builds an ``NXlog`` group whose *datasets* are `link` modules pointing into
        an ``NXlog`` published elsewhere in the file -- deep links to the value and time
        of one that already exists, rather than a link to the group itself. That is what
        lets the group carry attributes of its own, which it must when it is part of an
        ``NXtransformations`` chain and needs a ``transformation_type`` and a ``vector``
        the original has no reason to have.

        Not to be confused with the filewriter's ``link`` module, which is what the
        datasets inside it are; :func:`niess.nexus.streams.link_specifier` writes those.

        .. note::

           This assumes there *is* an ``NXlog`` elsewhere to point at -- somewhere an
           f144 module is publishing the parameter. Where that is not true the group has
           to be written directly instead, carrying its own value and time rather than
           links to someone else's. Nothing in niess needs that yet, and when something
           does this is where the choice belongs.
        """
        from ..nexus.streams import linked_nxlog
        return linked_nxlog(name, f'{self.nxlog_root}/{parameter}', attrs=attrs)

    def axis(self, owner, key: str, knob):
        """Where one driven axis's numbers come from.

        Every translator asks this and no translator answers it. A jaw's edge and the
        tank's a4 are the same question, and they used to be answered in two places --
        `_transformations` read `Motor.source` directly while the aperture went through
        `streams` -- so a mode switch could only ever have covered one of them.
        """
        return self.streams.bind(owner, key, self.as_motor(knob))

    def as_motor(self, knob):
        """A knob as a Motor, whichever spelling it arrived in."""
        from ..components.motor import Motor
        if isinstance(knob, Motor):
            return knob
        return self.instrument_parameter_to_motor(knob)

    def instrument_parameter_to_motor(self, parameter: InstrumentParameter):
        from ..components.motor import Motor, unquote
        name = parameter.name
        default = parameter.value.value if parameter.value.is_constant else None
        # The unit is unquoted here, the one point a McCode unit enters the NeXus side:
        # `InstrumentParameter.unit` is the four characters `"m"`, and a NeXus unit is
        # `m`. Cleaning at the sink instead would hide which producer was dirty.
        return Motor(name=name, unit=unquote(parameter.unit), source=name,
                     topic=DEFAULT_STREAM_TOPIC, default=default)

    def place(self, node: dict) -> str:
        """Put a node directly under NXinstrument, and say where it went.

        For the things that are neither components nor children of one: an
        `NXpositioner` for a motorised frame has to sit here, because `NXcomponent`
        does not accept one and the frame it drives is an `NXcomponent`. `NXinstrument`
        does accept one, which is the whole reason this can be this simple.

        Deliberately not `emit`: that registers a name in the flow graph, and a
        positioner is not in the beam.
        """
        name = node_name(node)
        if name in self.placed:
            raise ValueError(f'{name!r} is already directly under {INSTRUMENT_PATH}')
        self.placed.add(name)
        add_child(self.instrument_group, node)
        return f'{INSTRUMENT_PATH}/{name}'

    def positioner_name(self, emitted: str, axis: str, knob) -> str:
        """What to call the positioner a motorised frame hangs from.

        The name the frame is emitted under, and the axis's: `tank_mounting_a4`. Not
        the knob's name alone -- two frames may be turned by one named knob, and they
        cannot share a positioner because the chain each hangs from differs.
        """
        return f'{emitted}_{getattr(knob, "name", None) or axis}'

    def motor_log(self, name: str, parameter: str, attrs: dict | None = None) -> dict:
        """An NXlog for a named run-time value that is not a positioner axis.

        Chopper speed and delay come through here. They are knobs, but not motor
        records: ESS spells a chopper as eight logs off a `{root}:Spd_R`-style root,
        which is a different canonical shape from a positioner's three and is not yet
        written. So these keep the simulation's own names in both modes.
        """
        from ..nexus.streams import motor_group
        return motor_group(name=name, source=parameter,
                           topic=DEFAULT_STREAM_TOPIC, attrs=attrs)

    def flow(self):
        """The particle flow through the instrument, built once and kept.

        McCode has no way to say a beam branches, which is why the route this replaced
        had to be *handed* the real flow. A niess instrument states it -- BIFROST's tank
        declares ten paths leaving the sample -- so it is read off the tree here.
        """
        if self._flow is None:
            self._flow = self.instrument.to_graph()
        return self._flow

    def neighbours(self, visit) -> tuple[list, list]:
        """What feeds this node and what it feeds, under their emitted names.

        The graph is keyed on tree paths and the file is written in emitted names, so a
        node the conversion did not write cannot be named. Stepping *over* it rather than
        dropping it is what keeps the chain intact: a composite that only contains
        things, or a component that is a simulation device rather than part of the
        instrument, sits in the flow without appearing in the file, and what it joins
        stays joined.
        """
        graph = self.flow()
        if visit.id not in graph:
            return [], []
        return (self._nearest_written(graph, visit.id, graph.predecessors),
                self._nearest_written(graph, visit.id, graph.successors))

    def _nearest_written(self, graph, start, step) -> list:
        """The closest written nodes in one direction, over any that were not."""
        written, found, seen = self.emitted_names, [], {start}
        queue = list(step(start))
        while queue:
            node = queue.pop(0)
            if node in seen:
                continue
            seen.add(node)
            if node in written:
                if written[node] not in found:
                    found.append(written[node])
            else:
                queue.extend(step(node))
        return found

    def stream_group(self, selection: dict, name: str = 'data') -> dict:
        """One monitor's or detector's data stream, as the instrument chose it."""
        from ..nexus.streams import stream_group_from_selection
        return stream_group_from_selection(name, selection)

    def depends_on(self, frame) -> str:
        """What a thing in ``frame`` hangs from, as a NeXus path.

        The chain is the chain of frames the tree declares. Nothing here reads an
        emitted instrument to work out what depends on what.
        """
        if frame is None:
            return '.'
        return self.paths.get(frame, '.')


def _transformations(visit: Visit, position, rotation_deg, name: str) -> tuple[list, str]:
    """A component's placement, as an NXtransformations group and a depends_on.

    ``name`` is the name the group will actually be written under, which is not always
    ``visit.name``: a translator may rename what it emits, and BIFROST's do -- one visit
    to ``channel_1_1`` emits ``channel_1_1_monochromator`` and ``channel_1_1_triplet``.
    Naming the chain links from the visit instead pointed all 90 of them at a group
    nobody ever wrote.

    Emitted relative to whatever the thing hangs from, which is what the tree already
    says. `niess.nexus` reaches for absolute orientations and then subtracts an origin
    back out, because an emitted instrument gives it no frames to hang from.
    """
    from scipp import norm
    from mccode_antlr.common import InstrumentParameter
    from ..components.motor import Motor

    context = visit.context
    parent = context.depends_on(visit.frame)
    children = []
    previous = parent

    length = float(norm(position).to(unit='m').value)
    if length:
        direction = [float(v) for v in (position / norm(position)).value]
        children.append(dataset(
            'translation', length, dtype='double',
            attrs={'units': 'm', 'transformation_type': 'translation',
                   'vector': direction, 'depends_on': previous}))
        previous = f'{INSTRUMENT_PATH}/{name}/transformations/translation'

    for axis, angle in zip(('x', 'y', 'z'), rotation_deg):
        is_knob = isinstance(angle, (Motor, InstrumentParameter))
        if not is_knob and not angle:
            continue
        vector = [1.0 if axis == a else 0.0 for a in ('x', 'y', 'z')]
        attrs = {'units': 'degrees', 'transformation_type': 'rotation',
                 'vector': vector, 'depends_on': previous}

        if isinstance(angle, Motor):
            from .streams import positioner_group
            # The ESS shape: the positioner's reading *is* the transformation. Writing
            # a transformation that copies the positioner would be two names for one
            # number, and the copy is the one every reader would end up trusting.
            #
            # It goes beside the frame rather than inside it because `NXcomponent` does
            # not accept an `NXpositioner` and `NXinstrument` does. The chain threads
            # through it: the positioner's `value` carries this axis's transformation
            # attributes, and whatever hangs off the frame names that `value`.
            binding = context.axis(visit.obj, axis, angle)
            path = context.place(positioner_group(
                binding, name=context.positioner_name(name, axis, angle),
                depends_on=previous, transform=attrs))
            previous = f'{path}/value'
            continue
        if isinstance(angle, InstrumentParameter):
            from ..nexus.streams import linked_nxlog
            root = getattr(visit.context, 'nxlog_root', '')
            children.append(linked_nxlog(f'rotation_{axis}', f'{root}/{angle.name}', attrs=attrs))
        else:
            children.append(dataset(f'rotation_{axis}', float(angle), dtype='double', attrs=attrs))

        previous = f'{INSTRUMENT_PATH}/{name}/transformations/rotation_{axis}'

    if not children:
        # `previous`, not `parent`: a motorised axis is written as a positioner beside
        # this component rather than as a child here, so there can be nothing in
        # `children` and still be a chain end to hand back. In every other case
        # `previous` is `parent`, because it only advances when something is appended.
        return [], previous
    return [group('transformations', nx_class='NXtransformations', children=children)], previous


def component_body(nx_class: str, children=None, attrs=None, name=None,
                   position=None, rotation=None) -> dict:
    """What a translator returns: the class and contents of one component's group.

    ``position`` and ``rotation`` state where the thing sits in the frame it hangs from,
    for the composites that have no placement of their own -- an analyzer is at its
    frame's origin, turned by the Bragg angle; a detector is a distance along its.
    Anything with a position and an orientation of its own is placed by those.
    """
    return {'nx_class': nx_class, 'children': list(children or []),
            'attrs': dict(attrs or {}), 'name': name,
            'position': position, 'rotation': rotation}


def _placed(visit: Visit, body: dict) -> dict:
    """One component's group, with its placement attached."""
    from ..components.frame import Frame
    from ..spatial import mccode_ordered_angles

    from scipp import vector

    obj = visit.obj
    if body.get('position') is not None or body.get('rotation') is not None:
        position = body.get('position')
        position = vector([0., 0., 0.], unit='m') if position is None else position
        rotation = body.get('rotation')
        angles = (0.0, 0.0, 0.0) if rotation is None else rotation
    elif isinstance(obj, Frame):
        position, angles = obj.position, obj.angles()
    elif hasattr(obj, 'position'):
        position, angles = obj.position, mccode_ordered_angles(obj.orientation)
    else:
        # a composite with no placement of its own sits at its frame's origin
        position, angles = vector([0., 0., 0.], unit='m'), (0.0, 0.0, 0.0)

    name = body.get('name') or visit.name
    transformations, depends = _transformations(visit, position, angles, name)
    # A child that asked to sit exactly where its component sits can be told where that
    # is now, and only now: `depends` is the chain end the placement just produced.
    children = [resolve_same_place(child, depends) for child in body['children']]
    children += transformations
    # Always, even when this component adds no transformation of its own. `depends`
    # is the parent's link in that case, and dropping it detached the component from
    # the chain entirely: a wedge or a cassette sitting at exactly zero degrees said
    # nothing about hanging off the tank, so it did not turn when a motorised mounting
    # above it did. NeXus lets depends_on name a transformation in another group, so
    # the link is all that is needed -- there is no identity transformation to invent.
    # A component with nothing above it gets '.', which is how NeXus spells that.
    children.append(dataset('depends_on', depends))
    node = group(name, nx_class=body['nx_class'], children=children)
    for key, value in body['attrs'].items():
        node = add_child(node, attribute(key, value)) if False else node
    visit.context.paths[visit.id] = depends
    return node


def emit(visit: Visit, body: dict) -> None:
    """Put one component's group into the instrument."""
    context = visit.context
    node = _placed(visit, body)
    context.emitted_names[visit.id] = node_name(node)
    context.pending.append((visit, node))
    add_child(context.instrument_group, node)


def to_nexus_structure(instrument, registry=None, nxlog_root: str | None = None,
                       streams=None) -> dict:
    """Convert ``instrument`` to ESS NeXus Structure JSON.

    ``streams`` says where a driven axis's numbers come from: ``SIMULATED`` (the
    default) writes the simulation's own parameter names, ``REAL`` writes the EPICS
    positioners the components declare. One tree, two files; see
    :mod:`niess.nexus.bindings`.
    """
    from .bindings import as_streams
    context = NexusContext(
        instrument=instrument,
        nxlog_root=DEFAULT_NXLOG_ROOT if nxlog_root is None else nxlog_root,
        streams=as_streams(streams))
    walk(instrument, NEXUS_REGISTRY if registry is None else registry, context=context)
    # once, at the end: what feeds what is not known until everything has a name
    for visit, node in context.pending:
        for direction, names in zip(('inputs', 'outputs'), context.neighbours(visit)):
            if names:
                # Datasets, not attributes. NXcomponent declares `inputs` and `outputs`
                # as fields, so every class extending it inherits them as fields, and a
                # validator reading the NXDL rejects them written any other way.
                # One name is written as a string rather than a list of one, which is
                # what the standard and every reader of these files expect.
                add_child(node, dataset(direction,
                                        names[0] if len(names) == 1 else names))
    entry = group('entry', nx_class='NXentry',
                  children=[context.instrument_group])
    return {'children': [entry]}


def translator(*classes):
    """Register a function returning a component body for one or more niess classes."""
    def decorate(func):
        def run(visit: Visit):
            body = func(visit)
            if body is not None:
                emit(visit, body)
            return body

        holder = type(func.__name__, (), {'leaf': staticmethod(run),
                                          '__doc__': func.__doc__})
        for klass in classes:
            NEXUS_REGISTRY.register(klass)(holder)
        return func

    return decorate


#: What a group with a place and no content of its own says it is. NeXus has no class
#: for "a named point other things hang from": `NXcoordinate_system`, which this used to
#: write, describes the axes of a coordinate system rather than a thing standing in one,
#: and `NXinstrument` does not list it as a child it accepts. `NXcomponent` is the base
#: every instrument component extends, so it is the honest answer -- a component of the
#: instrument, with nothing to record but where it is -- and `description` says so in
#: the file rather than leaving a reader to infer it from the empty group.
REFERENCE_FRAME_DESCRIPTION = (
    'reference frame: a named position and orientation in the instrument, carrying no '
    'content of its own'
)


def _reference_frame() -> dict:
    """A component that is only a place: a declared frame, a sample position, a window."""
    return component_body(
        'NXcomponent',
        children=[dataset('description', REFERENCE_FRAME_DESCRIPTION)])


def _slit_angle(disc) -> list:
    """The opening width, when there is one width to state.

    `NXdisk_chopper` has a single `slit_angle`, so a disc whose openings differ has
    nothing to put in it -- the widths are in `slit_edges`, where they belong. Written
    only when every opening agrees, rather than picking one and calling it the answer.
    """
    widths = {round(closing - opening, 9) for opening, closing in disc.slits()}
    if len(widths) != 1:
        return []
    return [dataset('slit_angle', widths.pop(), dtype='double',
                    attrs={'units': 'degrees'})]


def _da00_config(topic: str, source: str, bins: int) -> dict:
    """The da00 configuration for a monitor's histogram.

    mccode_to_kafka stays the source of truth for the schema; this only says what this
    monitor's histogram looks like.
    """
    from mccode_to_kafka.writer import da00_dataarray_config, da00_variable_config
    axes = {
        'signal': {'unit': 'counts', 'label': f'{source} counts', 'shape': [bins]},
        'errors': {'unit': 'counts', 'label': f'{source} count errors', 'shape': [bins]},
        't': {'unit': 'microsecond', 'label': 'time since reference',
              'shape': [bins + 1]},
    }
    configs = {name: da00_variable_config(**spec, name=name, axes=['t'],
                                          data_type='float64')
               for name, spec in axes.items()}
    # da00_dataarray_config returns a whole {'module', 'config'} directive; what a
    # stream selection wants is the config inside it.
    directive = da00_dataarray_config(topic=topic, source=source,
                                      variables=[configs['signal'], configs['errors']],
                                      constants=[configs['t']])
    return directive.get('config', directive)

def register_defaults() -> None:
    """Attach the per-type translators. Called on import; separate so it reads as a list."""
    from ..components.aperture import Aperture
    from ..components.chopper import DISC_CHOPPERS
    from ..components.component import Component
    from ..components.filter import Filter
    from ..components.frame import Frame
    from ..components.monitors import FrameMonitor
    from ..components.source import Source

    @translator(Component)
    def marker(visit):
        """Anything with a place but nothing else to say: a sample position, a window."""
        return _reference_frame()

    @translator(Frame)
    def frame(visit):
        """A declared coordinate frame is a place to hang things, and nothing else."""
        return _reference_frame()

    @translator(Source)
    def source(visit):
        return component_body('NXmoderator')

    @translator(Filter)
    def filtered(visit):
        return component_body('NXfilter')

    # No @translator(Guide): each guide class writes its own `__nexus_leaf__`, because
    # what an NXguide needs is the shape of the channel and the m-value of every face
    # of it, and only the class knows what its channel looks like. The generic one that
    # used to be here wrote `length` and a scalar `m_left`/`m_right`/`m_top`/`m_bottom`,
    # none of which is a field NXguide has.

    @translator(Aperture)
    def aperture(visit):
        """An opening. Where its edges are driven at run time, they are links."""
        obj, context = visit.obj, visit.context
        from .streams import positioner_group
        children = [
            # The jaw's motors are where the jaw is: an edge is driven within the
            # opening, not moved relative to it. `SAME_PLACE` is the aperture's own
            # chain end, which the aperture cannot name until it has been placed.
            positioner_group(context.axis(obj, edge, parameter),
                             name=edge, depends_on=SAME_PLACE)
            for edge, parameter in getattr(obj, 'edge_parameters', lambda: {})().items()
        ]
        # TODO insert NXoff representation of the aperture?
        #      this would require knowing the extent of the absorbing section
        #      when McStas (and thus niess) only knows the opening size
        return component_body('NXaperture', children)

    @translator(FrameMonitor)
    def monitor(visit):
        """A monitor, and how its data reaches the file.

        The choice is the instrument's -- histograms or events -- and it is recorded on
        the monitor. Left unset, a frame monitor histograms, which is what these have
        always done.
        """
        obj, context = visit.obj, visit.context
        children = [dataset('description', visit.name)]
        selection = obj.stream
        if selection is None:
            from ..components.monitors import beam_monitor_topic
            topic = beam_monitor_topic(context.instrument.name)
            selection = {'module': 'da00', 'topic': topic, 'source': visit.name,
                         'config': _da00_config(topic, visit.name, obj.time_bins())}
        children.append(context.stream_group(selection))
        return component_body('NXmonitor', children)

    @translator(*DISC_CHOPPERS)
    def disc_chopper(visit):
        """One disc, however many McStas components it would take to simulate it.

        Registered for every class in `DISC_CHOPPERS`, not just one: they are siblings,
        and a disc registered under only its sibling's name falls through to the bare
        `Component` translator and comes out as a reference frame with a description --
        no openings, no speed, no delay. Silently, because an unregistered type is not an
        error. That is what happened to all six BIFROST discs.

        This is the case that drove the whole refactor. A disc whose openings are
        neither identical nor evenly spaced cannot be a single McStas DiskChopper, so
        it becomes one per opening -- and `niess.nexus` puts it back together by reading
        group tags out of METADATA those components carry, tags invented for this and
        then read by three targets. Here the disc is a disc: it never came apart.
        """
        obj = visit.obj
        context = visit.context
        from .streams import chopper_logs
        return component_body('NXdisk_chopper', [
            dataset('slits', len(obj.slits())),
            # What a run sets, so the file says where to read it rather than guessing.
            # Eight logs against a real controller, and the handful a simulation can
            # honestly fill otherwise -- see `chopper_logs`.
            *chopper_logs(obj, context.streams.chopper(obj)),
            # the standard's convention, not niess' looser one: positive,
            # increasing, opening edge first, only the last edge past 360
            dataset('slit_edges', obj.nexus_slit_edges(), dtype='double',
                    attrs={'units': 'degrees'}),
            *_slit_angle(obj),
            dataset('beam_position',
                    float(obj.beam_angle.to(unit='deg').value),
                    attrs={'units': 'degrees'}),
            dataset('radius', float(obj.radius.to(unit='m').value),
                    attrs={'units': 'm'}),
            dataset('slit_height', float(obj.height.to(unit='m').value),
                    attrs={'units': 'm'}),
        ])

register_defaults()
