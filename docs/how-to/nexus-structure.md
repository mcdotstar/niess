# Produce NeXus Structure JSON

`niess.nexus` turns a McCode instrument into the JSON the ESS
[kafka-to-nexus filewriter](https://github.com/ess-dmsc/kafka-to-nexus) consumes. It
works on an instrument niess built and on a `.instr` file it has never seen, because it
runs on the assembled `mccode_antlr` instrument, not on niess objects.

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
from niess.nexus import load_instr

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
| `nu = chopperspeed` | a `rotation_speed` **group** of links into `/entry/parameters/chopperspeed` |
| `nu = chopperspeed * 2` | an `NXcollection` holding the expression and a link per dependency |

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

## Absolute `depends_on`

`absolute_depends_on=True` rewrites every relative `depends_on` as an absolute NeXus
path. Use it when the consumer resolves paths from the file root rather than from the
group holding them.
