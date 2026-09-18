"""Filewriter stream and link module directives.

These are plain ``{'module': .., 'config': {..}}`` dicts. ``moreniius`` had to wrap
them in ``NotNXdict`` to smuggle them through ``nexusformat``; with no intermediate
object model there is nothing to smuggle them through.
"""
from __future__ import annotations

from typing import Any

from .nodes import dataset, group, stream

# Datasets an f144 module writes into its NXlog, which a link module can mirror.
# The commented entries trip a NeXus library failure in kafka-to-nexus.
NXLOG_LINK_DATASETS = (
    'alarm_message',
    'alarm_severity',
    'alarm_time',
    # 'average_value',
    'connection_status',
    'connection_status_time',
    'cue_index',
    'cue_timestamp_zero',
    'description',
    # 'maximum_value',
    # 'minimum_value',
    'time',
    'value',
)


def link_specifier(name: str, source: str) -> dict:
    """A filewriter ``link`` directive placing ``source`` at ``name``."""
    return stream('link', {'name': name, 'source': source})


def nxlog_data_links(source: str) -> list[dict]:
    """Link directives mirroring every dataset of an f144-populated NXlog."""
    return [link_specifier(name, f'{source}/{name}') for name in NXLOG_LINK_DATASETS]


def linked_nxlog(name: str, source: str, attrs: dict | None = None) -> dict:
    """An NXlog group whose datasets are links into an f144-populated NXlog."""
    return group(name, 'NXlog', children=nxlog_data_links(source), attrs=attrs)


def f144_log(name: str, source: str, topic: str, units: str, dtype: str,
             attrs: dict[str, Any] | None = None) -> dict:
    """One NXlog filled by an f144 stream.

    The units are written twice on purpose and neither is redundant. ``value_units`` is
    the transport contract: it is a key the ESS f144 config schema requires, and a config
    carrying only ``unit`` -- which is not a key that schema declares at all -- is
    rejected. The ``units`` attribute *on the module* is what a reader resolving a
    transformation chain looks at first. Both are written from one already-cleaned
    string, so they cannot disagree; cleaning only one of them is how a silently wrong
    unit becomes a loudly conflicting one.

    Nothing goes on the group. A transformation's units belong to its values, and its
    values live in the module.
    """
    return group(name, nx_class='NXlog', attrs=attrs, children=[stream(
        'f144',
        {'source': source, 'topic': topic, 'dtype': dtype, 'value_units': units},
        {'units': units} if units else None,
    )])


def motor_group(name: str, source: str, topic: str, attrs: dict[str, Any] | None = None,
                default=None, units: str | None = None,
                dtype: str | None = None) -> dict:
    """An NXlog for a streamed value, taking its units and dtype out of ``attrs``.

    Takes them out without mutating: this used to ``pop`` them off the caller's dict, so
    a caller reusing one dict across two axes silently lost the units on the second.
    """
    attrs = dict(attrs or {})
    units = attrs.pop('units', units)
    dtype = attrs.pop('dtype', dtype)
    if dtype is None:
        # Never None in the emitted config: dtype is a required f144 key, and a null
        # one is rejected outright rather than defaulted by the reader.
        from .nodes import convert_type
        dtype = convert_type(default)[0] if default is not None else 'double'
    return f144_log(name, source, topic, units or '', dtype, attrs or None)


def tdct_log(name: str, source: str, topic: str,
             attrs: dict[str, Any] | None = None) -> dict:
    """One NXlog filled by a `tdct` stream of top-dead-centre timestamps.

    Unlike `f144`, a `tdct` config carries no dtype and no units: the schema is a name
    and a vector of absolute nanoseconds, and there is nothing else to say about it. The
    wrapper carries ``default="time"`` because the timestamps *are* the data -- a reader
    opening the group wants the time axis, not a value axis.
    """
    attributes = dict(attrs or {})
    attributes.setdefault('default', 'time')
    return group(name, nx_class='NXlog', attrs=attributes,
                 children=[stream('tdct', {'source': source, 'topic': topic})])


#: The ESS canonical NXdisk_chopper: eight logs, in this order. `top_dead_center` is
#: third, not first, and the order is compared exactly -- a group that carries all eight
#: in another order is reported just as loudly as one that is missing some.
#:
#: The second element of each entry is the PV suffix the ESS chopper controller serves
#: that quantity on. `top_dead_center` is the odd one out twice over: it is a `tdct`
#: stream rather than `f144`, and its suffix is per-chopper rather than fixed, so it
#: comes from the disc instead of from here.
CHOPPER_LOGS = (
    ('rotation_speed', ':Spd_R', 'Hz'),
    ('rotation_speed_setpoint', ':Spd_S', 'Hz'),
    ('top_dead_center', None, None),
    ('delay', ':TotDly', 'ns'),
    ('experiment_delay', ':ChopDly-S', 'ns'),
    ('mechanical_delay', ':MechDly-S', 'degrees'),
    ('pulse_delay', ':BeamPosDly-S', 'ns'),
    ('park_angle', ':Pos_R', 'degrees'),
)


#: The ESS canonical NXpositioner: three logs, in this order. `value` is what the axis
#: reads, `target_value` what it was told, `idle_flag` whether it got there.
POSITIONER_LOGS = ('value', 'target_value', 'idle_flag')


def chopper_logs(disc, binding) -> list[dict]:
    """The NXlog children of one disc's NXdisk_chopper.

    Real: all eight canonical logs, sourced off the disc's controller. `top_dead_center`
    is a `tdct` stream on the disc's own TDC channel; the rest are `f144` on fixed
    suffixes. Getting all eight right is what lets the validator recover the PV root at
    all -- it infers the root from the TDC source, so a group without one cannot even be
    offered an automatic fix.

    Simulated: only the logs a simulation can honestly fill. There is no setpoint
    distinct from the value, no electronics to delay anything, and the numbers a
    simulation does have are its own parameter names rather than PVs. What it can say is
    how fast the disc turns, when the mark passes, and -- when parked -- where it
    stopped.

    The McStas delay is deliberately *not* written as `delay`. ESS `delay` is
    `{root}:TotDly`, the chopper's total electronic delay in nanoseconds; the McStas one
    is when the disc's zero mark reaches the beam, in seconds. Writing the second under
    the first's name would be read as the first by everything downstream, so a simulated
    file records it as `mark_delay` instead -- an unexpected log the layout check will
    mention, which is the honest cost of not lying.
    """
    topic = binding.topic
    if not binding.canonical:
        return [
            f144_log('rotation_speed', disc.speed_parameter(), topic, 'Hz', 'double'),
            tdct_log('top_dead_center', f'{disc.name}_tdc', topic),
            f144_log('mark_delay', disc.delay_parameter(), topic, 's', 'double'),
            f144_log('park_angle', disc.park_parameter(), topic, 'degrees', 'double'),
        ]

    root = binding.pv_root
    logs = []
    for name, suffix, units in CHOPPER_LOGS:
        if suffix is None:
            logs.append(tdct_log(name, f'{root}:{binding.tdc_channel}', topic))
        else:
            logs.append(f144_log(name, f'{root}{suffix}', topic, units, 'double'))
    return logs


def positioner_group(binding, name: str, depends_on: str = '.',
                     transform: dict[str, Any] | None = None) -> dict:
    """An NXpositioner for one driven axis.

    Real: the three canonical logs, sourced ``{pv_root}.RBV``, ``.VAL`` and ``.DMOV``.
    Simulated: ``value`` alone, because a simulation has no setpoint and no done flag --
    the parameter *is* the position. The group is the same shape either way, so nothing
    reading the file has to know which kind of run produced it.

    ``transform``, when given, is the transformation attributes the ``value`` log
    carries: the ESS pattern where a positioner's reading *is* the transformation,
    rather than a separate transformation copying it and becoming the number everyone
    trusts instead.
    """
    sources = binding.sources()
    # Units never ride on a transformation's group. They belong to its values, and the
    # values live in the module -- which `f144_log` fills from `binding.units` anyway,
    # so a caller handing us transformation attributes cannot put them in the wrong
    # place by including them.
    transform = {k: v for k, v in (transform or {}).items() if k != 'units'} or None
    children = []
    for log in POSITIONER_LOGS:
        source = sources.get(log)
        if source is None:
            continue
        idle = log == 'idle_flag'
        children.append(f144_log(
            log, source, binding.topic,
            units='' if idle else binding.units,
            dtype='int64' if idle else binding.dtype,
            attrs=dict(transform) if (transform and log == 'value') else None))
    children.append(dataset('depends_on', depends_on))
    return group(name, nx_class='NXpositioner', children=children)


def ev44_event_data_group(name: str, source: str, topic: str, attrs: dict | None = None) -> dict:
    """An NXevent_data group fed by an ev44 event stream."""
    return group(
        name,
        'NXevent_data',
        children=[stream('ev44', {'source': source, 'topic': topic})],
        attrs=attrs,
    )


def da00_data_group(name: str, config: dict, attrs: dict | None = None) -> dict:
    """An NXdata group fed by a da00 histogram stream.

    ``config`` is the da00 dataarray configuration -- build it with
    ``mccode_to_kafka.writer.da00_dataarray_config``, which stays the source of
    truth for the da00 schema.
    """
    return group(name, 'NXdata', children=[stream('da00', config)], attrs=attrs)


def resolve_stream(translation, default: dict | None = None, name: str = 'data') -> dict | None:
    """The stream group for a component, or ``None`` if it publishes nothing.

    The protocol is never chosen here. Some monitors belong on ``da00`` histograms
    and some on ``ev44`` events; which one is a property of the instrument setup, so
    it is read from the instrument in priority order:

    1. a ``METADATA "nexus_structure_stream_data"`` block on the component -- the
       escape hatch for instruments authored outside niess, emitted verbatim;
    2. a ``nexus_stream`` entry in the component's niess provenance ``extra``,
       which is how a niess component records the choice made when the instrument
       was built;
    3. ``default`` -- the component type's established behaviour, used only when
       the instrument expressed no preference at all.

    A component with no selection and no default gets no stream group rather than a
    guessed one.
    """
    from json import JSONDecodeError, loads

    for metadata in translation.instance.metadata:
        if metadata.mimetype != 'application/json':
            continue
        if metadata.name != 'nexus_structure_stream_data':
            continue
        try:
            return stream_group_from_config(name, loads(metadata.value))
        except JSONDecodeError:
            continue

    selection = None
    if translation.provenance is not None:
        selection = translation.provenance.extra.get('nexus_stream')

    if selection is None:
        selection = default
    if selection is None:
        return None

    return stream_group_from_selection(name, selection)


def stream_group_from_selection(name: str, selection: dict) -> dict:
    """Build a stream group from a ``{'module':.., 'topic':.., 'source':..}`` choice."""
    module = selection.get('module')
    if module is None:
        raise ValueError(f'Stream selection {selection!r} names no module')

    if module == 'ev44':
        return ev44_event_data_group(name, selection['source'], selection['topic'])
    if module == 'da00':
        config = selection.get('config')
        if config is None:
            config = {k: v for k, v in selection.items() if k != 'module'}
        return da00_data_group(name, config)
    if module == 'link':
        return group(name, 'NXdata', children=[
            link_specifier(selection.get('name', name), selection['source']),
        ])

    # An unrecognised module is still a legitimate filewriter directive
    return stream_group_from_config(name, {
        'module': module,
        'config': selection.get('config', {k: v for k, v in selection.items() if k != 'module'}),
    })


def stream_group_from_config(name: str, config: dict, attrs: dict | None = None) -> dict:
    """Wrap a pre-built ``{'module':.., 'config':..}`` blob in its natural group.

    Used for ``METADATA "nexus_structure_stream_data"`` payloads carried by
    instruments authored outside niess, where the module is chosen by whoever
    wrote the ``.instr`` file.
    """
    module = config.get('module')
    nx_class = {'ev44': 'NXevent_data', 'da00': 'NXdata'}.get(module, 'NXdata')
    return group(name, nx_class, children=[config], attrs=attrs)
