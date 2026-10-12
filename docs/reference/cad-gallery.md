# CAD gallery

Each kind of solid `niess.brep` draws, taken from a real instrument's assembly by its
label -- so each is exactly what a STEP export of that instrument contains. Drag to
turn a model, scroll to zoom. [Export an instrument to CAD](../how-to/export-to-cad.md)
says how to make your own.

<div class="grid cards" markdown>

-   **ESS butterfly moderator**

    <model-viewer src="../assets/cad-gallery/moderator.glb" alt="ESS_butterfly&#x27;s outline for BIFROST&#x27;s beam port, W4, as tall as the moderator" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    ESS_butterfly's outline for BIFROST's beam port, W4, as tall as the moderator. `moderator` in the BIFROST instrument.

-   **Elliptic guide**

    <model-viewer src="../assets/cad-gallery/elliptic_guide.glb" alt="BIFROST&#x27;s neutron beam optics assembly: four substrate walls following the ellipse" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    BIFROST's neutron beam optics assembly: four substrate walls following the ellipse. `nboa` in the BIFROST instrument.

-   **Straight guide**

    <model-viewer src="../assets/cad-gallery/straight_guide.glb" alt="One segment of BIFROST&#x27;s curved guide" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    One segment of BIFROST's curved guide. `unit_3_curved_guide_0` in the BIFROST instrument.

-   **Disc chopper (NXdisk_chopper)**

    <model-viewer src="../assets/cad-gallery/nx_disk_chopper.glb" alt="A pulse-shaping disc: one opening, centred on the beam at the disc&#x27;s reference angle" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    A pulse-shaping disc: one opening, centred on the beam at the disc's reference angle. `pulse_shaping_chopper_1` in the BIFROST instrument.

-   **Disc chopper (DiskChopper)**

    <model-viewer src="../assets/cad-gallery/disc_chopper.glb" alt="The teaching instrument&#x27;s single-opening disc" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    The teaching instrument's single-opening disc. `chopper` in the teaching instrument.

-   **Jaws**

    <model-viewer src="../assets/cad-gallery/jaw.glb" alt="A divergence slit, drawn at its opening" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    A divergence slit, drawn at its opening. `divergence_slit_1` in the BIFROST instrument.

-   **Slit**

    <model-viewer src="../assets/cad-gallery/slit.glb" alt="The sample-area mask, drawn at its opening" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    The sample-area mask, drawn at its opening. `mask` in the BIFROST instrument.

-   **Attenuator**

    <model-viewer src="../assets/cad-gallery/attenuator.glb" alt="A filter-style block at its size" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    A filter-style block at its size. `attenuator_1` in the BIFROST instrument.

-   **Radial collimator**

    <model-viewer src="../assets/cad-gallery/radial_collimator.glb" alt="One wedge of the tank: the beryllium filter and collimator arcs" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    One wedge of the tank: the beryllium filter and collimator arcs. `wedge_0` in the BIFROST instrument.

-   **Rowland analyzer**

    <model-viewer src="../assets/cad-gallery/analyzer.glb" alt="Each blade on the Rowland circle through sample, analyzer and detector, turned to focus" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    Each blade on the Rowland circle through sample, analyzer and detector, turned to focus. `channel_1_1_analyzer` in the BIFROST instrument.

-   **Detector triplet**

    <model-viewer src="../assets/cad-gallery/triplet.glb" alt="Three He-3 tubes" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    Three He-3 tubes. `channel_1_1_detector` in the BIFROST instrument.

-   **Named position**

    <model-viewer src="../assets/cad-gallery/named_position.glb" alt="Three short axes, for a bare Component that marks a place" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    Three short axes, for a bare Component that marks a place. `sample_origin` in the BIFROST instrument.

-   **BIFROST's secondary spectrometer**

    <model-viewer src="../assets/cad-gallery/tank.glb" alt="Nine channels of radial collimators, analyzers and triplets, at a4 = 0" camera-controls touch-action="pan-y" shadow-intensity="0.6" style="width: 100%; height: 260px; background: #eef1f4; border-radius: 4px"></model-viewer>

    Nine channels of radial collimators, analyzers and triplets, at a4 = 0. `tank` in the BIFROST instrument.

</div>

`TaperedGuide` and `NCrystalFilter` are drawn too -- a tapered box shell and a block at
the filter's size -- but neither instrument here has one.

A component with no shape of its own is placed and not drawn: windows, filters and
monitors, for now. The models are generated by
[`docs/examples/cad_gallery.py`](https://github.com/mcdotstar/niess/blob/main/docs/examples/cad_gallery.py)
when the site is built.
