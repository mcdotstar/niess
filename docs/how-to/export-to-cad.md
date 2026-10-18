# Export an instrument to CAD (STEP)

`niess.brep` draws a niess instrument as solid geometry: a
[build123d](https://build123d.readthedocs.io) assembly, which can be written to a STEP
file for any CAD program or shown in a viewer such as
[OCP CAD Viewer](https://github.com/bernhard-42/vscode-ocp-cad-viewer). Like every niess
target it reads the tree: a component's position and orientation are on the component,
and the frames it hangs from place it, so the solids land where McStas and NeXus put
the same components.

It needs the `brep` extra, which installs build123d:

```bash
pip install "niess[brep]"
```

## Write a STEP file

```python
--8<-- "export_to_cad.py:export"
```

Each component is a named part of the file -- `moderator`, `pulse_shaping_chopper_1`,
`channel_3_1_analyzer` -- under groups that follow the instrument's tree.

## Set the instrument's parameters

An instrument's run-time knobs are drawn at their declared defaults. Some of them move
things: BIFROST's detector tank turns by `detector_tank_angle` (a4), its sample by
`sample_rotation` (a3) and tilts by `goniometer_lower` and `goniometer_upper`. Give their values, in degrees, by name:

```python
--8<-- "export_to_cad.py:parameters"
```

`save_step` takes the same `parameters`. A name nothing turns by is refused rather than
ignored, since a misspelt one would otherwise draw the default without complaint:

```python
--8<-- "export_to_cad.py:refused"
```

## Find a part

`to_assembly` returns the assembly itself. It has one child per drawn component,
labelled with the name the component is given in McStas and NeXus, inside a group for
each node of the tree that holds more than one drawn thing:

```python
--8<-- "export_to_cad.py:tree"
```

A part that a component is drawn as several of -- an analyzer's blades, a triplet's
tubes -- is labelled within it: `blade_0`, `tube_2`.

## View it

The assembly can be shown directly, for example in VS Code with OCP CAD Viewer
(`pip install ocp_vscode`), where the tree appears as the viewer's object tree and each
part can be shown, hidden and picked on its own:

```python
from niess.bifrost import bifrost
from niess.brep import to_assembly
from ocp_vscode import show

show(to_assembly(bifrost.BIFROST, parameters={'detector_tank_angle': 60}))
```

## What is drawn

[The CAD gallery](../reference/cad-gallery.md) shows each kind of solid niess draws.
A component niess has no shape for is placed but not drawn: today that is windows,
filters and monitors. A disc chopper is drawn at its reference orientation -- its phase
belongs to a moment in time, not to a drawing -- and 1 cm thick, since its description
does not say.

Only instruments niess built can be drawn: every target reads the tree, and a `.instr`
file has none. See
[Converting an instrument niess did not build](convert-an-instrument.md#converting-an-instrument-niess-did-not-build).
