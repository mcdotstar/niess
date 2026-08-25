# Convert an instrument

An instrument is a tree, and every target reads the same walk over it. This is what that
looks like from the outside.

## Say what the instrument is

An `Instrument` names its pieces and says what each hangs from.

```python
--8<-- "one_instrument_many_targets.py:build"
```

BIFROST's primary is described in global coordinates, so it hangs from nothing. Its tank
is described about the sample — the first analyzer sits at `[1.189, 0, 0]`, not 162 m
down the guide — so it hangs from `sample_origin`, which the primary provides.

`origin` names the component everything is measured against. Targets need it, and
saying it once here is better than each of them guessing.

!!! tip "A piece can be turned at run time"

    `Mount(..., rotation=(0, a4, 0))` turns a piece about the frame it hangs from, in
    degrees. The three angles may be numbers or `InstrumentParameter`s, because the
    interesting ones are set per run: a BIFROST run turns the sample by `a3` and the
    detector tank by `a4`. McStas emits an `Arm` turned by the named parameter; NeXus
    emits a transformation linking to that parameter's `NXlog`.

## Convert it

=== "McStas"

    ```python
    --8<-- "one_instrument_many_targets.py:mccode"
    ```

=== "NeXus"

    ```python
    --8<-- "one_instrument_many_targets.py:nexus"
    ```

    Instrument-specific translators are opt-in per conversion. `BIFROST_REGISTRY` gives
    its analyzers and detectors their ICD pixel numbering; without it they fall back to
    the generic classification, which places them correctly but does not classify them.

=== "tof"

    ```python
    --8<-- "one_instrument_many_targets.py:tof"
    ```

    `origin` is where the `tof.Source` sits, which belongs to the model rather than the
    instrument: an ESS source in `tof` carries a 0.05 m facility offset while the niess
    moderator is at the instrument origin.

=== "CAD"

    ```python
    from niess.brep import save_step

    save_step(bifrost, 'bifrost.step')
    ```

## Ask the instrument about itself

The tree answers questions an emitted instrument cannot.

**Where the beam branches.** McCode describes an instrument as a list, so the only flow
it can express is declaration order. BIFROST's tank branches:

```python
--8<-- "one_instrument_many_targets.py:flow"
```

Ten paths leave the sample — nine channels and the elastic monitor — and a neutron takes
one. That is what NeXus states through each group's `inputs` and `outputs`.

**What a thing will be called, and what it is measured from.**

```python
--8<-- "one_instrument_many_targets.py:names"
```

`analyzer.emit_name('monochromator')` is `channel_3_1_monochromator`, and its frame is
the arm's own `analyzer_point`. A translator asks rather than rebuilding the name from
an f-string, which is how the same name used to get written in two places and drift.

## Converting an instrument niess did not build

The tree-reading targets need a tree. For a `.instr` file there isn't one, and the
older instrument-reading entry points remain for that, each under `via_instr` in its own
package: `niess.nexus.via_instr.to_nexus_structure`,
`niess.brep.via_instr.instrument_to_assembly`, `niess.tof.via_instr.to_tof_model` and
`niess.chopcalc.narrow_source_wavelengths` all take an assembled instrument and recover
what they can from it. See [Translate a McStas `.instr`](translate-an-instr.md) for
turning one into a niess submodule, which is the better answer where it is available.
