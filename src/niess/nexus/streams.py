"""Filewriter stream and link module directives.

These are plain ``{'module': .., 'config': {..}}`` dicts. ``moreniius`` had to wrap
them in ``NotNXdict`` to smuggle them through ``nexusformat``; with no intermediate
object model there is nothing to smuggle them through.
"""
from __future__ import annotations

from .nodes import group, stream

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


def motor_group(name: str, source: str, topic: str, attrs: dict | None = None) -> dict:
    """A NXlog group constructed to hold a NXpositioner value or NXtransformations entry

    The group has a list of attributes including the NX_class, depends_on,
    transformation_type, and vector,
    while its children consists only of the stream definition module, which specifies
    the units of the logged value in two ways

    {'name':..., 'type':'group', 'attributes':[
            {'name':'NX_class', 'values':'NXlog', 'dtype':'string'},
            {'name':'depends_on', 'values':..., 'dtype':'string'},
            {'name':'transformation_type', 'values':..., 'dtype':'string'},
            {'name':'vector', 'values':[...], 'dtype':'float'}
        ],
        'children':[{
            'module':'f144',
            'config':{'dtype':..., 'source':..., 'topic':..., 'value_units'=...},
            'attributes':{'name':'units', 'values:..., 'dtype':'string'}
        }]
    }
    """
    dtype = (attrs or {}).pop('dtype', None)
    units = (attrs or {}).pop('units', None)
    return group(
        name,
        nx_class='NXlog',
        children=[stream(
            'f144',
            {'source': source, 'topic': topic, 'unit': units, 'dtype': dtype},
            {'units': units}
        )],
        attrs=attrs,
    )


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
