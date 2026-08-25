# Build a new instrument submodule

This guide builds `niess.teaching`, a complete but deliberately small instrument: a
moderator, two guide units in their own section, a chopper, a jaw, a monitor and a
sample position. It ships with niess, so you can read every file referenced here, and
it is assembled and converted by the test suite, so none of it can quietly stop working.

`niess.bifrost` is the real-world example. It is the same patterns at 358 components,
which is why this guide does not start there.

## What you are writing

```
src/niess/teaching/
├── __init__.py       what the submodule exports
├── parameters.py     the numbers: one calibration dictionary per section
└── primary.py        the structure: which components, in what order
```

The split matters. `parameters.py` holds measured quantities and nothing else;
`primary.py` holds structure and nothing else. A recalibration touches only the first,
and a design change touches only the second.

## 1. Declare the structure

A `Section` is an ordered list of typed fields. There is no method to write:

```python
--8<-- "src/niess/teaching/primary.py:sections"
```

Two rules that are easy to get wrong and quiet when you do:

!!! warning "Declaration order is beam order"

    `Section.from_calibration` constructs its fields **positionally**, in the order
    they are declared here, so the declaration order must match the physical beamline.

    The calibration dictionary's *key* order does not matter: each field is looked up
    by name. The dictionaries in this package happen to be written in beam order too,
    which makes them easier to read against the class, but nothing enforces it.

!!! note "Underscored fields are extras, not components"

    A field whose name starts with `_` is a per-class setting rather than a component,
    and is invisible to `parts()`, `types()`, `items()` and `field_types()`. Add as
    many as your section needs. They carry defaults, so msgspec requires them **after**
    the fields that do not — which is why `_flat` is declared last.

`_flat = True` means "emit into the assembler I was given". Without it a section nests
itself: `Guides` has no `_flat`, so it becomes an included sub-instrument called
`teaching_guides` — `assembler.included(f'{assembler.name}_guides')`.

## 2. Write the calibration

Every dimensional quantity is a scipp `Variable` with the unit the drawing uses.
Nothing converts to metres here; that happens once, in `__mccode__`.

A component's `position` and `orientation` are its placement in the instrument
coordinate system. How you arrive at them is up to you.

`niess.bifrost` chains them, because that is how its geometry is specified: each
element so far past the one before it. Each section builder takes the position and
orientation of what came before, places its own components relative to that with
`niess.spatial.at_relative`, and returns the reference for what comes next — the direct
analogue of `AT (0, 0, d) RELATIVE previous`:

```python
--8<-- "src/niess/teaching/parameters.py:chain"
```

Because the chain is computed rather than typed, moving the guide moves everything
downstream of it and no number is written twice.

!!! tip "Chaining is a convenience, not a requirement"

    If you already know where things are — from a survey, a CAD model, or an existing
    instrument definition — put those coordinates in the calibration directly and skip
    `at_relative` entirely:

    ```python
    --8<-- "direct_positions.py:direct"
    ```

    That produces the same instrument as the chained calibration, to the last bit.
    Chain when the geometry is genuinely specified as a chain of offsets, so that
    moving one element carries the rest with it; write coordinates out when they are
    known independently and a chain would only obscure them. The two styles can be
    mixed within one instrument.

Three quantities in the teaching instrument are *run-time* values rather than
constants, and each gets there differently:

- `source_lambda_min` / `source_lambda_max` — passed in the calibration as McCode
  parameter specification strings (`'source_lambda_min/"angstrom" = 0.75'`), which
  `ESSource` turns into `DEFINE INSTRUMENT` arguments.
- `chopperspeed` / `chopperdelay` — `DiscChopper` declares these itself.
- `jaw_l` / `jaw_r` — `Jaw` declares these itself.

You only need `ensure_runtime_line(assembler, 'name/"unit" = default')` when writing
your own component that needs a knob no existing class provides.

## 3. Assemble it

```python
--8<-- "build_teaching.py:assemble"
```

That produces exactly seven McStas components and six instrument parameters. The
[example asserts both](https://github.com/mcdotstar/niess/blob/main/docs/examples/build_teaching.py),
so this page cannot drift from what the code does.

## Writing a component

If nothing in [the component reference](../reference/components.md) fits, a new
`Component` subclass is three things:

1. **Typed fields** for its calibrated properties, as scipp `Variable`s.
2. **`from_calibration(cls, cal)`** pulling each field out of the dictionary, with
   defaults and any accepted aliases.
3. **`__mccode__(self)`** returning `(component_type_name, parameters)` — and this is
   the *only* place units are converted, with `.to(unit='m').value`.

Optionally `__mccode_role__()` and `__mccode_extra__()`, which record what the thing is
in the provenance metadata that the CAD and NeXus adapters dispatch on.

### Contributing to the instrument around it

`__mccode__` says what the component *is* — one `COMPONENT` line and its parameters.
Real components often need more than that from the instrument they sit in: a knob the
operator can turn, a value worth computing once at start-up, a lookup table, a flag that
later components read.

Overriding `to_mccode` is the supported way to add those. Do the work, then delegate:

```python
--8<-- "component_to_mccode.py:component"
```

The helpers, and what each one writes into the generated instrument:

| call | lands in | use it for |
| --- | --- | --- |
| `ensure_runtime_line(a, 'name/"unit" = default')` | `DEFINE INSTRUMENT(...)` | a knob settable at run time |
| `ensure_runtime_parameter(a, parameter)` | `DEFINE INSTRUMENT(...)` | the same, from an `InstrumentParameter` you already hold |
| `a.declare('double name;')` | `DECLARE` | an internal variable with instrument scope |
| `a.initialize('name = ...;')` | `INITIALIZE` | computing that variable once, before the first neutron |
| `a.declare_array('double', name, values)` | `DECLARE` | a lookup table too large to inline |
| `ensure_user_var(a, 'int', name, description)` | `USERVARS` | a per-particle flag later components read |
| `ensure_registry(a, 'owner/repo@version')` | the component search path | a `.comp` McStas does not ship |
| `a.metadata(name, mimetype, value)` | a `METADATA` block | information for a downstream consumer, such as a stream configuration |

All of the `ensure_*` helpers are idempotent by name: two instances of the same class
can each ask for the same user variable or registry, and the second is a no-op. An
*inconsistent* repeat — the same parameter name with a different default or unit —
raises rather than silently picking one.

Anything derived from the component's own calibration should be computed in Python and
emitted as a literal. Reserve `DECLARE`/`INITIALIZE` for values that depend on a
run-time parameter, as `gate_window` does above, since those genuinely cannot be known
until the instrument runs.

Three worked patterns in the shipped library, in increasing order of involvement:

- `niess/components/aperture.py::Jaw` — declares two run-time parameters, then delegates.
- `niess/components/chopper.py::DiscChopper` — the same, plus `zero_angle`/`beam_angle`
  for a component whose centre is off the beam axis.
- `niess/components/guide.py::EllipticGuide` — emits its per-segment m-values as
  `DECLARE`d arrays when the guide is segmented.
- `niess/components/monitors.py::FrameMonitor` — pulls in an external component
  registry and attaches stream metadata.

## Composites: when one object is several components

A detector bank is one niess object and many McStas instances. So is a chopper disc
whose openings are unevenly spaced: McStas' `DiskChopper` describes `nslit` *identical,
evenly spaced* openings, so an irregular disc has to be emitted as one `DiskChopper`
per opening.

niess ships that case as `DiscChopper` with several `windows`, and it is the shortest
complete example of a composite -- a disc with one opening emits a single component, and
the same class emits a group when it has more. Its calibration is the `NXdisk_chopper`
description, so the same numbers serve McStas and NeXus:

| | |
| --- | --- |
| `zero_angle` | where the disc's reference mark sits, as an angle from the local **+y** axis (`top_dead_center` in `NXdisk_chopper`, and accepted under that name) |
| `beam_angle` | where the beam crosses the disc, as an angle from that mark — **180** for a disc that hangs above the beam (`beam_position` in `NXdisk_chopper`) |
| `windows` | the angular edges of the openings, measured from the mark |

Every angle is positive counter-clockwise viewed facing **+z** — looking downstream —
and the edges are positive and increasing, two per opening. An opening that straddles
the mark at zero delay closes *beyond* 360 rather than wrapping round to a smaller
number, so the pairs stay ordered and each width is just the difference:

```python
--8<-- "group_composite.py:build"
```

Three McStas components come out, sharing one `packspeed` and one `packdelay` — one
physical disc, so one pair of run-time knobs — and all three in a single McStas
`GROUP`, named after the disc.

!!! warning "Alternatives, not a series"

    The `GROUP` is what makes the emission correct. A `DiskChopper` absorbs whatever
    misses its slit, so three ungrouped choppers in a row would demand a neutron be
    inside all three openings at once and transmit essentially nothing. Grouped, they
    are tried in turn and the neutron passes if it clears any one of them.

    Any composite that emits alternatives rather than a sequence needs the same:
    `instance.GROUP(name)`, with a name derived from the object's own — instance names
    are unique within an instrument, so a name-derived group is unique too. Each carries its own width, and its own
`delay` offset: a McStas `delay` is when an opening's centre is at the beam, so an
opening centred at 20 degrees from the mark, with the beam at 90, arrives 70 degrees of
rotation later. The opening straddling the mark is centred at 360 and arrives after 90.

How long 70 degrees takes depends on the speed, and a disc that turns the other way
covers the *other* 290 degrees to get there — neither is known until the simulation
runs. So the angles are computed when the instrument is built and the arithmetic is
left to the generated C, one start-up variable per opening:

```c
double pack_slit_0_delay;
pack_slit_0_delay = packdelay + (packspeed < 0 ? 290.0 : 70.0) / (360.0 * fabs(packspeed));
```

An opening already at the beam skips the variable: it is there at `packdelay` whichever
way the disc spins.

### Making the group recoverable

Splitting the disc is a McStas implementation detail. A NeXus file wants one
`NXdisk_chopper` and a CAD model wants one solid, so each instance is tagged with what
an adapter needs to reverse the split:

```python
--8<-- "group_composite.py:tags"
```

```
pack_slit_0    role=disc-opening-primary    group=pack index=0 edges=[10.0, 30.0]
pack_slit_1    role=disc-opening-member     group=pack index=1 edges=[100.0, 140.0]
pack_slit_2    role=disc-opening-member     group=pack index=2 edges=[350.0, 370.0]
```

| what | why |
| --- | --- |
| `disc_group_id` | which instances belong to the same physical object |
| `disc_group_index` | their order within it |
| `slit_edges` | this instance's own contribution to the whole |
| `role` | which instance stands for the group, and which are folded into it |

Tag by explicit role rather than by position: an adapter reads the instrument as a flat
list, and nothing guarantees the primary comes first.

`niess.nexus` ships the matching translator, registered against the component's *niess
source type* — the first dispatch tier — so no configuration is needed. The primary
instance rebuilds the disc from its siblings; the members return `None`, which means
emit nothing. The rebuilt group takes the disc's own name, since `pack_slit_0` describes
how the instrument was built rather than what it contains:

```python
--8<-- "group_composite.py:result"
```

Without that translator the same instrument still converts, as the three separate discs
the McStas file literally describes. Grouping is an enrichment, not a prerequisite.

`niess.brep` dispatches through the same three tiers, so one role builder there rebuilds
the disc as a single solid for CAD from the same tags. The mechanism in full, including
how to write these for your own composite, is in
[Write NeXus translators](custom-nexus-registry.md#many-instances-one-nexus-group).

### Writing your own

The shape to copy is `niess/components/chopper.py::DiscChopper.to_mccode`: it calls
`assembler.component(...)` once per instance and tags each one.

### A composite that needs something around its contents

A composite often needs more than components: a coordinate frame to hang them from, a
user variable they share, an `%include` to put them in. Those go in `__mccode_enter__`,
which runs before the composite's children are emitted, and `__mccode_exit__`, which
runs after and closes whatever was opened.

```python
class Cassette(Base):
    detectors: tuple[He3Tube, ...]

    def __mccode_enter__(self, visit):
        assembler = visit.context.assembler
        frame = assembler.component(f'{visit.name}_arm', 'Arm',
                                    at=((0, 0, 0), visit.frame),
                                    rotate=((0, self.angle.value, 0), visit.frame))
        add_niess_metadata(frame, self, source_name=f'{visit.name}_arm',
                           role='reference-frame')
        for child in visit.children():          # put the contents in that frame
            visit.context.frames[child.id] = frame
        return frame
```

`visit` is the composite's place in the instrument: `visit.name` is what it is called,
`visit.frame` what it hangs from, `visit.index` its position among its siblings, and
`visit.ancestor(SomeClass)` the enclosing thing of a given kind. Returning
`niess.walk.SKIP` from `__mccode_enter__` means the composite emits its own children
itself, which is what `Arm` does — its two frames interleave with its two components,
so they cannot be walked in order.

Nothing has to be registered anywhere. Everything a class contributes to a McStas
instrument is written on the class:

| on the class | for |
| --- | --- |
| `__mccode__` | what the thing *is*: one `COMPONENT` line and its parameters |
| `to_mccode` | contributing to the instrument around it — see [above](#contributing-to-the-instrument-around-it) |
| `__mccode_enter__` | what a composite needs around its contents |
| `__mccode_exit__` | closing whatever that opened |

A translator can also be *registered* against a class, which then wins over the class's
own hooks. That is for the cases a method cannot serve: extending a class you do not
own, or scoping a conversion so that importing a module does not change some other
instrument's output — the same reason `niess.nexus` keeps BIFROST's translators off the
shared registry.

!!! danger "Tag every instance you build by hand"

    `Component.to_mccode` tags what it emits; hand-built instances are yours to tag.
    Forget it and nothing fails. The instance simply becomes invisible to every
    adapter — missing from the STEP assembly, missing from the NeXus file — with no
    error to notice. `tests/test_provenance_coverage.py` enforces this for niess's own
    composites.

Two more rules for composites:

- **`ensure_registry(assembler, 'owner/repo@version')`** for components McStas does not
  ship. Prefer a tag over `@main`: `@main` is not reproducible for anyone who builds
  your instrument later.
- **Never derive a name from `assembler.name`.** Inside a nested section that is the
  *section's* name. Use `instrument_name(assembler)`, which walks to the root. This is
  a real bug that shipped: monitors inside sections published to
  `bifrost_curved_beam_monitor`, a topic nothing subscribes to.

## Always pass `rotate=`

`to_mccode(assembler, at, rotate)` defaults an omitted `rotate` to `ABSOLUTE`. A
component positioned in a rotating frame but left rotated absolutely looks correct
until the frame turns, and then quietly points the wrong way. This shipped too — see
`tests/test_bifrost_tank.py::test_elastic_monitor_is_placed_and_rotated_in_the_tank_frame`.

## What you get for free

- **Serialisation** — `to_dict`/`from_dict` and `niess.io.json`, with scipp-aware
  equality. Register a top-level type in `MODEL_ENCODE` (`niess/io/utils.py`) to make
  it round-trip.
- **NeXus** — [conversion](nexus-structure.md) with no extra work, and
  [custom translators](custom-nexus-registry.md) when the defaults are not enough.
- **CAD** — a STEP assembly via `niess.brep`.

## Checklist

- [ ] `parameters.py` holds every number, as scipp `Variable`s, chained with `at_relative`
- [ ] Section fields are in beam order and match the calibration key order
- [ ] Underscored extras come after the component fields (msgspec requires it)
- [ ] Hand-built instances call `add_niess_metadata`
- [ ] Non-standard components call `ensure_registry`
- [ ] Names derive from `instrument_name(assembler)`, never `assembler.name`
- [ ] Every `to_mccode` call passes `rotate=`
- [ ] Top-level types registered in `MODEL_ENCODE` for JSON round-trip
- [ ] Tests mirroring `tests/test_bifrost_primary.py` and `tests/test_provenance_coverage.py`
