"""Beam monitors read out through the ESS ``cbm`` Event Formation Unit.

A real ESS beam monitor is one channel of a cbm EFU: a front-end node (FEN) and a channel
on it, a readout type, and the Kafka source the EFU publishes under. `CbmChannel` says
that much about one monitor, and is a fact about the instrument -- ECDC's EFU
configuration lists the same things for every monitor it reads.

Two things are built from it:

- McStas: with ``to_mccode(..., collect=Collect(...))`` every monitor that has a channel is
  followed by a ``Collector*`` component from mcstas-readout-master, which stores the rays
  the monitor counted. ``readout-replay`` later sends them to a cbm EFU as readout packets.
- The EFU: `efu_config` writes the cbm EFU's JSON configuration, so that the EFU the
  replay feeds and the file-writer reading it agree with the instrument about every
  monitor.

The NeXus file describes the stream the EFU publishes when it is written with
``to_nexus_structure(..., efu_monitors=True)``; otherwise a monitor keeps describing the
histogram McStas itself produces.
"""
from __future__ import annotations

from typing import Literal

import msgspec

#: ESS pulse period in nanoseconds, which is what the cbm EFU bins time-of-flight within
PULSE_PERIOD_NS = 71_428_571

#: The cbm EFU's own packet type, shared by every beam-monitor readout
CBM_TYPE_SUBTYPE = 0x10

#: The ring ECDC reserves for beam monitors. The EFU reads fibres 2N and 2N+1 as ring N.
MONITOR_RING = 11


class CbmChannel(msgspec.Struct, kw_only=True, frozen=True):
    """One beam monitor as a cbm EFU reads it.

    ``type`` is the EFU's readout type: ``EVENT_0D`` counts neutrons, ``IBM`` integrates a
    current, ``EVENT_2D`` adds a position. ``schema`` is what the EFU publishes: ``da00``
    histograms, summed over ``aggregated_frames`` pulses, or ``ev44`` events. The EFU will
    not histogram an ``EVENT_2D`` monitor.
    """
    fen: int
    source: str
    type: Literal['EVENT_0D', 'IBM', 'EVENT_2D'] = 'EVENT_0D'
    channel: int = 0
    schema: Literal['da00', 'ev44'] = 'da00'
    #: da00: the histogram's time bins, spanning ``max_tof_bin`` nanoseconds
    bin_count: int = 744
    max_tof_bin: int = PULSE_PERIOD_NS
    #: da00: how many pulses go into each published histogram
    aggregated_frames: int = 14
    #: ev44: the pixel number of the first (or only) pixel
    pixel_offset: int = 1
    #: ev44 EVENT_2D: the pixel grid
    width: int | None = None
    height: int | None = None
    #: What the NeXus file calls the stream, e.g. 'BIFROST Beam Monitor 1'
    title: str | None = None

    def __post_init__(self):
        if self.schema == 'da00' and self.type == 'EVENT_2D':
            raise ValueError(f'{self.source}: the cbm EFU can not histogram EVENT_2D '
                             f'readouts; use schema="ev44"')
        if self.type == 'EVENT_2D' and (self.width is None or self.height is None):
            raise ValueError(f'{self.source}: an EVENT_2D monitor needs width and height')

    def topology(self) -> dict:
        """This monitor's entry in the cbm EFU's ``Topology``."""
        entry = {'FEN': self.fen, 'Channel': self.channel, 'Type': self.type,
                 'Source': self.source, 'Schema': self.schema}
        if self.schema == 'da00':
            entry |= {'MaxTofBin': self.max_tof_bin, 'BinCount': self.bin_count,
                      'AggregatedFrames': self.aggregated_frames}
        elif self.type == 'EVENT_2D':
            entry |= {'PixelOffset': self.pixel_offset,
                      'Width': self.width, 'Height': self.height}
        else:
            entry |= {'PixelOffset': self.pixel_offset, 'PixelRange': 1}
        return entry

    def stream(self, topic: str) -> dict:
        """The stream selection for what the EFU publishes, as a NeXus file reads it.

        The da00 shape is the EFU's: a ``uint32`` ``signal`` over ``frame_time`` bin
        edges in nanoseconds. It is what ECDC binds for BIFROST's histogramming monitors.
        """
        selection = {'module': self.schema, 'topic': topic, 'source': self.source}
        if self.schema == 'da00':
            attributes = [{'name': 'axes', 'data': ['frame_time']}]
            if self.title is not None:
                attributes.append({'name': 'title', 'data': self.title})
            selection['config'] = {
                'topic': topic, 'source': self.source,
                'attributes': attributes,
                'variables': [{'name': 'signal', 'data_type': 'uint32',
                               'axes': ['frame_time'], 'shape': [self.bin_count],
                               'unit': 'dimensionless'}],
                'constants': [{'name': 'frame_time', 'data_type': 'int32',
                               'axes': ['frame_time'], 'shape': [self.bin_count + 1],
                               'unit': 'ns'}],
            }
        return selection


def as_channel(value) -> CbmChannel | None:
    """A channel from a calibration entry, which may hold one or its fields."""
    if value is None or isinstance(value, CbmChannel):
        return value
    return msgspec.convert(value, CbmChannel)


class Collect(msgspec.Struct, kw_only=True, frozen=True):
    """How ``to_mccode`` records monitor rays for replay.

    ``filename`` is the collector file every monitor writes to; unset, the collectors use
    their own default. ``keep_probability`` thins what a monitor records -- one value for
    every monitor, or a value per monitor name -- without biasing it: a kept ray carries
    its weight divided by the probability. ``registry``, when given, is where the
    ``Collector*`` components are found (any `niess.assembler.ensure_registry`
    specification); otherwise the assembler must already know them.
    """
    filename: str | None = None
    monitor_ring: int = MONITOR_RING
    keep_probability: float | dict[str, float] = 1.0
    registry: str | None = None

    def keep(self, name: str) -> float:
        if isinstance(self.keep_probability, dict):
            return self.keep_probability.get(name, 1.0)
        return self.keep_probability


#: The particle variables a monitor's EXTEND sets for the collector that follows it.
#: Shared by every monitor: a collector clears the flag once it has recorded.
HIT = 'cbm_hit'
FIBRE = 'cbm_fibre'


def collector(channel: CbmChannel, collect: Collect, name: str) -> tuple[str, dict]:
    """The ``Collector*`` component, and its parameters, recording one monitor's rays."""
    common = dict(ring=f'"{FIBRE}"', fen_value=channel.fen,
                  channel_value=channel.channel,
                  keep_probability=collect.keep(name))
    if collect.filename is not None:
        common['filename'] = f'"{collect.filename}"'
    if channel.type == 'EVENT_0D':
        return 'CollectorBM0', common
    if channel.type == 'IBM':
        # A simulated ray is one count: the EFU adds ADC / MCASum per readout
        return 'CollectorBMI', common | dict(adc_value=1, sum_value=1)
    raise NotImplementedError(f'{name}: collecting {channel.type} monitor readouts')


def emit_collector(context, instance, channel: CbmChannel, name: str):
    """Follow a just-emitted monitor ``instance`` with the collector recording its rays.

    The monitor's EXTEND marks a ray it counted, after whatever EXTEND the monitor was
    already given; the collector, at the same place, records only marked rays and then
    clears the mark. Nothing between them moves the ray, so the time it records is the
    time the monitor saw.
    """
    from .assembler import ensure_registry, root_assembler
    collect = context.collect
    assembler = context.assembler
    if collect.registry is not None:
        ensure_registry(assembler, collect.registry)
    # On the instrument, not the section: every monitor shares them, and a section
    # declaring its own would declare them again for each section with a monitor
    for declaration in (f'int {HIT};', f'int {FIBRE};'):
        root_assembler(assembler).ensure_user_var(declaration)
    mark = f'if (SCATTERED) {{ {HIT} = 1; {FIBRE} = {2 * collect.monitor_ring}; }}'
    instance.EXTEND(*instance.extend, mark)

    comp, parameters = collector(channel, collect, name)
    recorder = assembler.component(f'{name}_collector', comp,
                                   at=((0, 0, 0), instance.name),
                                   rotate=((0, 0, 0), instance.name),
                                   parameters=parameters)
    recorder.WHEN(HIT)
    recorder.EXTEND(f'{HIT} = 0;')
    return recorder


def monitor_channels(instrument) -> list[tuple[str, CbmChannel]]:
    """Every monitor in ``instrument`` that a cbm EFU reads, by name, in beam order."""
    from .components.monitors import FrameMonitor
    from .walk import visits
    return [(visit.name, visit.obj.readout) for visit in visits(instrument)
            if isinstance(visit.obj, FrameMonitor) and visit.obj.readout is not None]


def efu_config(instrument, *, monitor_ring: int = MONITOR_RING,
               max_tof_ns: int = 2 * PULSE_PERIOD_NS,
               max_pulse_time_diff_ns: int = PULSE_PERIOD_NS + 29) -> dict:
    """The cbm EFU's JSON configuration for ``instrument``'s monitors.

    ``max_tof_ns`` defaults to two pulse periods, as BIFROST's does. A FEN or channel
    claimed by two monitors is an error here, as it is to the EFU.
    """
    channels = monitor_channels(instrument)
    if not channels:
        raise ValueError(f'{instrument.name} has no monitor with a cbm channel')
    seen = {}
    for name, channel in channels:
        key = (channel.fen, channel.channel)
        if key in seen:
            raise ValueError(f'{name} and {seen[key]} both claim FEN {channel.fen} '
                             f'channel {channel.channel}')
        seen[key] = name
    return {
        'Detector': 'CBM',
        'TypeSubType': CBM_TYPE_SUBTYPE,
        'MaxPulseTimeDiffNS': max_pulse_time_diff_ns,
        'MaxTOFNS': max_tof_ns,
        'MonitorRing': monitor_ring,
        'MaxFENId': max(channel.fen for _, channel in channels),
        'Topology': [channel.topology() for _, channel in channels],
    }
