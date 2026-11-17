# Change BIFROST: from an .instr edit to niess

The BIFROST bundle attached to each niess release is an ordinary McStas instrument, and
editing a copy of it is fine for a study of your own. This page is for when the change
should be made where the model lives instead: to keep it, to share it, or to get the
NeXus structure and the other targets to agree with it. Each recipe starts from the edit
you would make to the `.instr` and gives the niess equivalent.

Every recipe ends with an instrument, `bifrost`, that you emit like the stock one:

```python
from niess.mccode import to_mccode
from mccode_antlr.io.json import save_json

save_json(to_mccode(bifrost, insert_provenance_metadata=False), 'bifrost.json')
```

and then `mccode-antlr extract` as in the bundle's README.

!!! note "Nothing to change for a parameter"
    Chopper speeds and phases, slit and jaw openings, attenuators, and the sample and
    detector-tank angles are instrument parameters. Set them on the `mcrun` command line;
    neither the `.instr` nor niess needs editing.

## Swap the sample

*In the `.instr`:* replace the `sample` Arm, a placeholder in the bundle, with a sample
component.

```python
--8<-- "bifrost_recipes.py:sample"
```

`niess.bifrost.samples` has helpers for McStas's own sample components: `vanadium`,
`powder`, `tunneling`, `spinwave`, `isotropic_sqw`, `crystal` and `crystal_sqw`. Pass
several to `sample(...)`, each with a `share`, to scatter from more than one. The
focusing on the analyzers and the elastic monitor, and the weights that go with it, are
worked out for you.

## Correct a calibrated value

*In the `.instr`:* change a number on one or more `COMPONENT` lines: a position, a
length, a coating.

Every BIFROST component is built from a calibration dictionary, so a correction is a
change to that dictionary:

```python
--8<-- "bifrost_recipes.py:calibration"
```

`primary_parameters()` holds the primary spectrometer, one entry per section and one per
component within it, named as in the `.instr`. The detector tank's calibration is
`niess.bifrost.parameters.tank_parameters()`. A correction that should become part of the
official model belongs in those functions; open an issue or a pull request.

## Add or remove a component

*In the `.instr`:* insert a `COMPONENT` line, or delete one.

niess has no API for this yet. A section's components are the fields of its class, in
beam order, so changing what a section holds means a section class with different fields.
These two helpers make one, and put it in place of the original:

```python
--8<-- "bifrost_recipes.py:resection"
```

### Add a monitor

`Opaque` is any McStas component, given by its type name and parameters, exactly as on a
`COMPONENT` line. Here a `PSD_monitor` goes 10 cm after the bandwidth monitor:

```python
--8<-- "bifrost_recipes.py:insert"
```

Positions inside the primary spectrometer's sections are in the instrument's coordinates,
so place a new component from a neighbour's `position` and `orientation`, as here.

### Remove a component

```python
--8<-- "bifrost_recipes.py:remove"
```

### Limits

- The new section class exists only in your session. It is not part of niess, so a
  niess release can rename or reorder the parts your code refers to.
- An `Opaque` emits McStas and nothing else: a NeXus structure gets its placement but no
  description, and CAD export has nothing to draw.
- If a structural change should be part of the official model, ask for it on niess
  rather than carrying the recipe. The section's class is then changed, and every target
  follows.

The sections of the primary spectrometer, in beam order, are `compressor`, `curved`,
`expanding`, `straight` and `closing`. `print(bifrost.parts[0].content.straight)` lists
what one contains.
