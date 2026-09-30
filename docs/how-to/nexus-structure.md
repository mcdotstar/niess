# Produce NeXus Structure JSON

`niess.nexus` turns a niess instrument into the JSON the ESS
[kafka-to-nexus filewriter](https://github.com/ess-dmsc/kafka-to-nexus) consumes. It reads
the tree: a component's position and orientation are on the component, and a declared
`Frame` is what a `depends_on` chain points at.

A `.instr` file has no tree, and converting one is not supported — see
[Converting an instrument niess did not build](convert-an-instrument.md#converting-an-instrument-niess-did-not-build).

## From a niess instrument

```python
--8<-- "teaching_to_nexus.py:convert"
```

`origin` names the component whose frame everything is placed against. Give it
explicitly: without it niess looks for a component of McStas category `samples`, warns
if there is none, and falls back to absolute positions.

## Reading an existing `.instr`

niess converts **niess instruments**. `to_nexus_structure` expects an instrument niess
built; translating a `.instr` that niess did not build is not supported, and the
`instr2ns` command that used to do it has been removed.

`load_instr` remains, because *reading* a file is useful even though translating it is
not. It reads `.instr`, `.json` and `.msgpack`, and returns an `mccode_antlr` `Instr`:

```python
from niess.io.mccode import load_instr

original = load_instr('my_instrument.instr')
for instance in original.components:
    print(instance.name, instance.type.name, instance.at_relative)
```

The intended use is checking a niess submodule against the hand-written file it replaces
— comparing resolved positions rather than text, since the two will never be
byte-identical. See [verify a translation](../examples/verify_translation.py) and
[build a new instrument submodule](new-instrument-submodule.md).

## Reading the output

The structure is `{'children': [entry]}`, with the instrument at
`/entry/instrument`. Each component becomes a group carrying a `transformations` chain
and a `depends_on` pointing into it. Two small readers save you walking dictionaries:

```python
--8<-- "teaching_to_nexus.py:inspect"
```

## Constants become values, run-time knobs become links

This is the distinction that matters most in the output. A component parameter that
folds to a constant is written as a value. One that depends on an *instrument*
parameter cannot be known until the instrument runs, so it is written as a link to the
`NXlog` where that parameter's value will be published:

| in the instrument | in the NeXus structure |
| --- | --- |
| `radius = 0.35` | a `radius` dataset holding `0.35` |
| `nu = chopper_rotation_speed` | a `rotation_speed` **group** of links into `/entry/parameters/chopper_rotation_speed` |
| `nu = chopper_rotation_speed * 2` | an `NXcollection` holding the expression and a link per dependency |

DECLARE'd instrument variables are folded before this decision, so a parameter written
in terms of one still becomes a literal.

## Choosing how a monitor streams

Some monitors belong on `da00` histograms, some on `ev44` events. That is a property of
the instrument, not of the translator, so niess never guesses. The choice is resolved
in this order:

1. a `METADATA "nexus_structure_stream_data"` block on the component — the escape hatch
   for instruments not built with niess;
2. a `nexus_stream` entry in the component's niess provenance, set when the instrument
   is built:

    ```python
    monitor.to_mccode(assembler, at=..., rotate=...,
                      nexus_stream={'module': 'ev44', 'topic': 'events', 'source': 'mon'})
    ```

3. the component type's established default.

A component with no selection and no default gets no stream group rather than a guessed
one. niess monitors attach a `da00` configuration by default, published to
`{instrument}_beam_monitor`; override the topic with `to_mccode(..., topic=...)`.

## Simulated and real files from one tree

A driven axis reads from somewhere. In a simulation that is a McCode parameter name; on
a real instrument it is an EPICS positioner, which ESS spells as three logs off one PV
root — `{root}.RBV` as `value`, `{root}.VAL` as `target_value`, `{root}.DMOV` as
`idle_flag`. Nothing about the instrument changes between the two, so the tree carries
the roots and the conversion decides whether to use them:

```python
from niess.nexus import to_nexus_structure, REAL

to_nexus_structure(bifrost)                 # simulated, the default
to_nexus_structure(bifrost, streams=REAL)   # against the real positioners
```

A component declares a root per axis, keyed the way it keys the axes themselves:

```python
Jaw.from_calibration({
    'name': 'divergence_slit_1',
    'pv_roots': {'left':  'BIFRO-DivSl1:MC-SlYp-01:Mtr',
                 'right': 'BIFRO-DivSl1:MC-SlYm-01:Mtr'},
    ...
})
```

and a `Motor` — what turns a mounting — carries its own:

```python
Motor(name='detector_tank_angle', unit='degrees', source='detector_tank_angle',
      topic='bifrost_motion', default=0.0, pv_root='BIFRO-DtCar:MC-RotZ-01:Mtr')
```

`pv_roots` is inert unless the file is written for a real run, so an instrument that
declares them still emits exactly the McStas it always did.

The group is the same shape in both modes. A simulation has no setpoint and no done
flag — the parameter *is* the position — so it writes `value` alone, and the ESS layout
check says so as a warning. That is a true statement about a simulated file rather than
a defect in it.

A real conversion **raises** on an axis with no root declared, because the alternative
is a plausible-looking simulated axis inside a file that claims to be real. An
instrument that is genuinely only half wired up can say so:

```python
from niess.nexus import RealStreams
to_nexus_structure(bifrost, streams=RealStreams(strict=False))
```

### A disc chopper

ESS spells an `NXdisk_chopper` as eight stream-fed logs off one controller, in a fixed
order, `top_dead_center` third. It is a `tdct` stream — a vector of absolute times, with
no dtype and no units — and its PV suffix is per-chopper rather than fixed, so the disc
carries it:

```python
DiscChopper.from_calibration({
    'name': 'pulse_shaping_chopper_1',
    'pv_root': 'BIFRO-ChpSy1:Chop-PSC-101',
    'tdc_channel': '00-TS-I',
    ...
})
```

That TDC source is what makes the rest diagnosable: the validator recovers a chopper's
PV root *from* it, so a group without one cannot even be offered an automatic fix.

A simulated disc writes only what a simulation knows — how fast it turns, when the mark
passes, and where it stopped if parked. There is no setpoint distinct from the value and
no electronics to delay anything, so those logs are absent and the ESS layout check says
so, truthfully.

The disc's delay is written as `delay`, in nanoseconds. ESS `delay` is
`{root}:TotDly`, the controller's total delay. A simulated disc has no electronics
adding to it, so its total delay is the one knob it has, which is declared in
nanoseconds for that reason — `{name}_delay/"ns"`. McStas works in seconds, so the
conversion happens where the knob is inserted into the component:
`delay = 1e-9 * {name}_delay`. The other delays a real controller reports have no
counterpart in a simulation and are not written.

### Where the timestamps are measured from

A top-dead-centre time is meaningless on its own — it is measured against a pulse. So
the instrument records its pulse reference times in the accelerator's `NXsource`, as
one sample per pulse of the proton current on target:

```text
/entry/instrument/source   NXsource
    current                NXlog  <- f144, one sample per pulse
    depends_on = "."
```

`source` and `current` are ECDC's names, which the real instrument's file uses. The
group describes the accelerator, not the moderator. A niess `Source` is the moderator,
and is written as an `NXmoderator` component under its own name (`moderator` in
BIFROST). The group hangs under `NXinstrument`: a group of this class directly under
`NXentry` does not validate.

Everything in the file — detector events, motor readbacks, chopper crossings — must
share these reference times, or none of them can be compared with each other.

### A motorised mounting

`NXcomponent` does not accept an `NXpositioner` child and `NXinstrument` does, so a
motorised frame's positioner sits *beside* the frame rather than inside it, and the
chain threads through it. The positioner's `value` log carries the transformation —
`transformation_type`, `vector` and `depends_on` on the group, `units` on the stream
module — and whatever hangs off the frame names that `value`:

```text
/entry/instrument/
  detector_tank_angle     NXpositioner
    value                 NXlog   @transformation_type=rotation @vector=[0,1,0]
    target_value          NXlog
    idle_flag             NXlog
  tank_mounting           NXcomponent
    depends_on = "/entry/instrument/detector_tank_angle/value"
```

The positioner is named for its knob, which is the name a facility gives it and binds
its streams to. A second frame turned by the same knob cannot share the positioner,
because the chain it hangs from differs, so its positioner is named for the frame as
well: `tank_mounting_detector_tank_angle`.

Writing a separate transformation that copied the positioner would be two names for one
number, and the copy is the one every reader would end up trusting.

## Streams from a facility bindings file

ECDC keeps, per instrument, a `bindings.yaml` that says which Kafka topic and source
fill each log of the real instrument's file. It is keyed by where the log sits below
`NXinstrument`:

```yaml
pulse_shaping_chopper_1.rotation_speed:
  schema: f144
  source: BIFRO-ChpSy1:Chop-PSC-101:Spd_R
  topic: bifrost_choppers
  dtype: double
  value_units: Hz
  source_type: forwarder
```

`BoundStreams` reads the answers from such a file rather than building them from a PV
root, so a per-disc TDC channel or a piezo motor's `PzMtr` record needs no special case.
For that to work niess names things as the file does. The file's key is then also the
path niess writes the log at, and no mapping between the two names is kept.

BIFROST carries a verbatim copy of ECDC's file:

```python
from niess.bifrost import BIFROST
from niess.bifrost.ecdc import bifrost_streams
from niess.nexus import to_nexus_structure
from niess.nexus.bifrost import BIFROST_REGISTRY

to_nexus_structure(BIFROST, registry=BIFROST_REGISTRY, streams=bifrost_streams())
```

The default is a simulation made to look like the real instrument:

- **Only what the simulation has is written.** That means a knob's `value`, a disc's
  speed, delay and park angle, the TDC times, and the pulse reference. A setpoint, a done
  flag, or a delay the electronics add has no counterpart in a simulation, and leaving
  them out is part of what says the file is simulated.
- **Every EPICS source is prefixed** with `mcstas:`. The file names the real topics, but
  `mcstas:BIFRO-ChpSy1:Chop-PSC-101:Spd_R` is never the real PV, so a simulated producer
  that reached the real network could not impersonate a real motor or chopper. A source
  an event formation unit chooses (`source_type: efu`, such as a triplet's
  `arc=0;triplet=0`) is fixed by the EFU and left as it is.
- **Each simulated log names its knob**, as a `simulation_parameter` attribute on the
  NXlog, because a source copied from the real instrument does not resemble the name of
  the parameter that feeds it.
- **A knob is declared in the unit its log is published in** — millimetres for a jaw
  edge, nanoseconds for a chopper delay, degrees for an angle — and converted to what
  McStas wants where it is inserted into a component. A knob declared in any other
  unit raises `UnitMismatch` instead of being converted silently.

`bifrost_streams(simulated=False)` writes the file for the real instrument: every bound
log, with the sources exactly as bound.

To refresh the copy, follow `src/niess/bifrost/ecdc/UPSTREAM.md`. Every binding must
either be written or be excused in `niess.bifrost.ecdc.NOT_SIMULATED`, with a reason.
`tests/test_bifrost_ecdc_bindings.py` checks this, so a binding ECDC adds or renames
fails the test rather than going missing from the file.
