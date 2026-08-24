# Install and first instrument

```console
pip install niess
```

niess needs Python 3.11 or newer. It pulls in `scipp` for units and geometry and
`mccode-antlr` for the McStas side.

## Build an instrument

`niess.teaching` is a small instrument that ships with niess. Building it means turning
its calibration into a McStas instrument:

```python
--8<-- "build_teaching.py:assemble"
```

`instrument` is an `mccode_antlr` object. `str(instrument)` is the `.instr` text, and
it can be compiled and run by McStas like any other.

Seven components come out of that: the moderator, two guide units, a chopper, a jaw, a
monitor and the sample position. So do six run-time parameters —
`source_lambda_min`, `source_lambda_max`, `chopperspeed`, `chopperdelay`, `jaw_l` and
`jaw_r` — which nothing had to declare by hand. The chopper and the jaw generate their
own, and the source wavelengths were given in the calibration as parameter
specifications rather than values.

## Convert it to NeXus

The same object converts to the JSON the ESS filewriter consumes:

```python
--8<-- "teaching_to_nexus.py:convert"
```

and its contents can be inspected without walking dictionaries by hand:

```python
--8<-- "teaching_to_nexus.py:inspect"
```

That yields `NXmoderator`, `NXguide`, `NXdisk_chopper`, `NXaperture`, `NXmonitor` and
`NXcoordinate_system` groups. The chopper's `rotation_speed` is not a number but a link
to an `NXlog`, because `chopperspeed` is settable at run time — see
[constants become values, run-time knobs become links](how-to/nexus-structure.md#constants-become-values-run-time-knobs-become-links).

## Next

- [Core concepts](concepts.md) — what a component, a section and a calibration actually are.
- [Build a new instrument submodule](how-to/new-instrument-submodule.md) — the teaching instrument, explained line by line.
- [Translate an existing `.instr`](how-to/translate-an-instr.md) — if you already have a McStas model.
