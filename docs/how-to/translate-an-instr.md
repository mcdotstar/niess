# Translate a McStas `.instr`

You have a working McStas model and want it as a `niess.{instrument}` submodule.
`niess-scaffold` does the mechanical part; this guide is about the part it cannot do.

```console
$ niess-scaffold my_instrument.instr -o src/niess --origin sample
```

That reads the instrument, resolves every placement, maps the components it recognises
onto niess classes, wraps the rest in [`Opaque`](../reference/components.md#unmodelled-components),
checks that everything still lands where the `.instr` puts it, and writes a package you
own and edit.

## What you gain, and what it costs

You gain calibration: quantities keep the units they were measured in, positions are
chained instead of repeated, and the same object emits McStas, NeXus and CAD. You also
gain a place to record things McStas has no concept of, such as which Kafka topic a
monitor publishes on.

The cost is real. The `.instr` file stops being the source of truth. If someone edits
it directly afterwards, the change is lost the next time the module is built. Decide
that up front.

## What the tool does not do

**It converts a small fraction of a real instrument.** The mapping is deliberately
limited to cases where the McStas component type *determines* the niess class. For
`ESS_IN5_reprate` that is 8 components of 50; the other 42 become `Opaque`. This is the
honest state of niess's component library rather than a limitation of the converter, and
the conversion report is a prioritised list of what is missing.

**It cannot recognise a composite.** BIFROST's 45 analyzers are one
`Monochromator_Rowland` each in the emitted file, and nothing can reconstruct
`Analyzer(blades=...)` from that. Recognising that several components are one device is
the work you are here to do.

**It cannot group.** You get one flat `Section`, because which components belong together
is a statement about the instrument.

**It cannot recover units or intent.** Everything is metres and degrees, because that is
all a `.instr` carries.

## What you get

```
src/niess/my_instrument/
    __init__.py         the conversion report, as the module docstring
    structure.py        a Section: every component, typed, in beam order
    parameters.py       the calibration, chained the way the .instr chained it
    instrument.py       instrument() -> Instrument
    test_placement.py   the check that everything is still where it was
    my_instrument.instr the file it came from
```

## Then do this, roughly in order

### 1. Replace `Opaque` components, most frequent first

Each `Opaque` is a component that emits McStas faithfully and tells no other target
anything. Replacing one with a real niess class is what makes NeXus and CAD able to say
something about it. Work down the report:

```
Still `Opaque`, most frequent first -- this is the to-do list:
    12  L_monitor
     7  PSD_monitor
     6  Guide
```

Look for a fit in [the component reference](../reference/components.md). If nothing fits,
writing a component is three methods — see
[Writing a component](new-instrument-submodule.md#writing-a-component). If the type is one
a *general* tool should always map the same way, add a recipe to
`niess/scaffold/recipes.py` instead, and every future conversion gets it.

### 2. Group into sections, in beam order

Contiguous components that do one job become a `Section`, which emits as a `%include`
rather than more lines in the top-level `TRACE`. Section *field* order must be beam order,
because `Section.from_calibration` constructs positionally; the calibration dictionary is
looked up by name, so its key order is yours to choose.

### 3. Re-express the numbers in the units they were measured in

`scalar(1.5, unit='m')` becomes `1500 * mm` if that is what the drawing says. Conversion
happens exactly once, at the `__mccode__` boundary, so nothing downstream cares.

### 4. Decide what should be run-time again

The report names the instrument parameters that drove geometry:

```
Instrument parameters that drove geometry and are now constants.
The geometry no longer follows them:
  GUI_start = 2
  TT = 50
```

These are written into `parameters.py` as named constants, so the relationships the author
expressed survive as Python — a component placed `AT (0, 0, GUI_start)` still reads
`vector([0.0, 0.0, GUI_start], unit='m')`. What is lost is that they are *knobs*. A
detector tank angle really should be run-time: make it a `Motor` on a `Mount`
(see [`niess.bifrost`](https://github.com/mcdotstar/niess/blob/main/src/niess/bifrost/bifrost.py)'s
`a3`/`a4`). A guide start distance really is fixed geometry: leave it a constant.

## Keep the test

`test_placement.py` asserts that every component in the original `.instr` is at the same
absolute position in what the module emits. It is the only thing that will tell you if
step 1, 2 or 3 moved something by a millimetre. It is *not* a text diff, and should not
become one:

> Do not diff the generated text against the original — it will never match, and should
> not: different names, different ordering, added metadata.

!!! warning "Two traps worth knowing about, because the tool hit both"

    **A component's own reference point.** A niess `DiscChopper`'s `position` is its
    *spindle*; the emitted `AT` is where the beam crosses the disc. So the generated
    `parameters.py` keeps two things apart: `at[...]` is where the `.instr` put each
    component and is what the chain is built from, while a chopper's `position` is
    `at[...]` plus the offset to its spindle. Chaining off the spindle instead would carry
    that offset into every component downstream.

    **`Instr.resolve_orientations()` is not a safe reference.** It loses the
    degrees-to-radians conversion on a *symbolic* rotation angle, so an instrument placed
    through `ROTATED (0, TT, 0)` resolves to `sin(TT)` with `TT` in degrees. `niess.scaffold`
    measures both sides with its own `placements` for that reason, and
    `check_against_mccode` refuses to use McStas as a reference where it cannot be trusted.

## Doing it by hand

Nothing here requires the CLI. `niess.scaffold` is an ordinary module:

```python
from niess.io.mccode import load_instr
from niess.scaffold import convert, summary, to_instrument, write

instr = load_instr('my_instrument.instr')
conversion = convert(instr, origin='sample')
print(summary(conversion))

instrument = to_instrument(conversion)   # the Instrument, with no source generated
write(conversion, 'src/niess')           # or the module
```

Reading an instrument without converting it at all is one call, which is how to take
stock before deciding whether to convert at all:

```python
--8<-- "inventory_instr.py:inventory"
```

And a submodule you wrote *by hand* deserves the same check the generated
`test_placement.py` does, against the file it replaces:

```python
--8<-- "verify_translation.py:verify"
```

`resolve_orientations()` is used there rather than `niess.scaffold`'s own `placements`
because the teaching instrument has no rotations at all. For anything that does, use
`niess.scaffold.verify.compare`, for the reason in the warning above.

## Checklist

- [ ] Conversion report read, and the `Opaque` list understood as the work queue
- [ ] Every `Opaque` either replaced, or deliberately left
- [ ] Components grouped into `Section`s in beam order
- [ ] Numbers re-expressed in the units of the drawing
- [ ] Frozen parameters either promoted back to run-time or accepted as fixed
- [ ] `test_placement.py` still passing, and committed
- [ ] The original `.instr` kept as a fixture
