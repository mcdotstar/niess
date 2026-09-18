# moreniius parity

!!! warning "Historical"

    The code this page audits has since been **removed**. niess converted McCode
    instruments to NeXus by reading the emitted instrument back; it converts niess
    instruments by reading the object tree, and once every target did that, the
    instrument-reading route was two thousand lines of reconstructing what the tree
    states. It went with the McStas demotion.

    This page is kept as the record of the port, because the port is why the NeXus
    output looks the way it does, and because the classification of differences below
    is still the argument for each of them. **The module paths named here no longer
    exist.** Nothing in niess reads a `.instr` to convert it — `niess.io.mccode.load_instr`
    still parses one so its placements can be inspected, which is a different thing.

niess replaced [`moreniius`](https://github.com/g5t/moreniius), which converted McCode
instruments to ESS NeXus Structure JSON through a `nexusformat` object model. This page
records what happened to every part of it, so nothing was lost silently.

The module paths below were relative to `niess/nexus/via_instr/`, the subpackage that
held the instrument-reading route.

The regression baseline that pins the two against each other, and the classification of
every remaining difference, is documented in
[the golden baseline notes](https://github.com/mcdotstar/niess/blob/main/tests/data/bifrost_nexus_structure_golden.md).

## Audit

Every public piece of `moreniius` (13 modules, ~2200 lines), and where it went. Nothing
is left unaccounted for: each entry is *ported*, *subsumed* (the need disappeared with
`nexusformat`), or *dropped* with a reason.

`moreniius` itself is untouched and still installable; retiring the repository is a
separate, human step.

## Ported

| moreniius | where it went (since removed) | Notes |
| --- | --- | --- |
| `mccode/orientation.py` — `NXPart`, `NXParts`, `NXOrient` | `orientation.py` | Same algebra, emitting transformation dicts instead of `NXfield`s |
| `mccode/instr.py` — `make_transformations`, `resolve_target`, `build_graph`, `inputs`/`outputs`, `guess_origin`, `to_nx` | `instrument.py::NexusContext` | `guess_origin` → `_find_origin`; `to_nx` → the `mcstas` dataset |
| `mccode/instr.py::expr2nx` | `expression.py::resolve` + `parameter_node` | Split into "decide" and "build"; returns a typed result rather than four unrelated shapes |
| `mccode/instance.py` — two-tier dispatch, `register_translator` | `registry.py` over `niess.dispatch.NiessRegistry` | Now three tiers (niess source type → niess role → McCode type); shared with `niess.brep`. Where `register_translator` mutated one global table, a registry may instead *extend* another via `parent=`, so instrument-specific translators are chosen per conversion with `to_nexus_structure(registry=...)` rather than by whatever the process imported |
| `mccode/instance.py` — `COMPONENT_*_TO_NEXUS`, `get_nx_type` | `instrument.py` — same maps, `default_nx_class` | |
| `mccode/instance.py` — `NEXUS_TO_COMPONENT` | `instrument.py::NEXUS_CLASS_PARAMETERS` + `fallback_body` | Only `NXfermi_chopper` ever populated anything; the other three entries mapped to `{}` |
| `mccode/comp.py` — `slit`, `guide`, `collimator_linear`, `diskchopper`, `elliptic_guide_gravity`, `monitor` translators | `translators.py` | |
| `additions.py` — `monochromator_rowland_translator`, `detector_tubes_offsets_and_one_cylinder`, `bifrost_detector_collector`, `Frame_monitor`, pixel/`WHEN` helpers | `bifrost.py`, on its own `BIFROST_REGISTRY` | The `ESS_butterfly` → `NXmoderator` mapping went to the generic table in `instrument.py` instead: `niess.components.source.ESSource` emits it for every instrument, not just BIFROST |
| `utils.py` — `ess_flatbuffer_specifier`, `ev44_event_data_group`, `link_specifier`, `nxlog_data_links`, `linked_nxlog` | `streams.py` | Minus `NotNXdict` |
| `utils.py::outer_transform_dependency` | `instrument.py` | Reads `depends_on` from node attributes |
| `writer.py::convert_types` | `nodes.py::convert_type` | Minus the `NXattr`/`NXfield` branches |
| `writer.py::_to_absolute` | `nodes.py::to_absolute` + `absolutize_depends_on` | The recursive rewrite is now its own pass rather than part of serialization |
| `nxoff.py` — `NXoff.from_wedge`, `sphere`, `to_nexus` | `off.py` | |
| `nexus_structure.py` — `load_instr` | `io/mccode.py` | Reading a file survives; see below for `convert`. It is not a NeXus concern, so it lives with the other McCode readers rather than under `nexus/` |
| `MorEniius.from_mccode` / `to_nexus_structure` | `to_nexus_structure(instr, ...)` | One function; there was never a reason for the two-stage object |

## Subsumed — the need disappeared with `nexusformat`

| moreniius | Why it is gone |
| --- | --- |
| `utils.NotNXdict` | Existed only to smuggle raw dicts through `NXfield`. Nothing to smuggle through now. |
| `writer.Writer` and `_to_json_dict` | The tree-walk that turned `nexusformat` objects into JSON. Translators build the JSON directly. |
| `utils.resolve_parameter_links` | Renamed a link's `config.name` after the fact. `parameter_node` names links correctly when it builds them. |
| `mccode/instance.NXInstance.make_nx` | Wrapped values in `NXfield`s. Also the source of the group-flattening bug documented in `tests/data/bifrost_nexus_structure_golden.md`. |
| `utils.dict2NXobj`, `_sanitize` | Rebuilt `nexusformat` objects from JSON blobs. |
| `only_nx` flag (threaded through nearly every function) | Meant "raise if a non-NeXus object is in the tree". There is no object tree. |

## Dropped, deliberately

| moreniius | Reason |
| --- | --- |
| `additions.readout_translator` and `BIFROST_DETECTOR_MODULES` | The translator's registration is commented out in `additions.py`, so the module-level cache was written on every detector translation and never read. Reviving it needs the `Readout` component to exist in an instrument first. |
| `additions.detector_tubes_only_cylinder` | Unregistered alternative giving each pixel its own cylinder. The registered variant (one shared cylinder plus per-pixel offsets) is ported. |
| `additions.bifrost_pixel_regex_20230703` | Superseded by the `..._20230911` variant, which is the one used. |
| `mccode/instr.py` `CTargetVisitor` re-run | Unnecessary *and* wrong — see `variables.py`. Replaced by parsing `Instr.declare` directly, which also fixes the DECLARE folding bug. |
| `NXInstance.dump_mcstas` | Debug flag, default off, never set by anything. |
| `utils.get_mcstasscript_component_eniius_data`, `decode_component_eniius_data`, `mccode_component_eniius_data` | The legacy `eniius_data` escape hatch: a JSON blob under METADATA name `eniius_data`/mimetype `json`, or scraped out of an EXTEND block with a regex. niess never used it (only a stale TODO in `components/monitors.py` mentioned it), and `nexus_structure_stream_data` supersedes it for the streaming case it was mostly used for. If a non-niess instrument ever needs arbitrary extra NeXus content per component, add it as a fourth tier in `streams.resolve_stream` rather than reviving the EXTEND-block regex. |
| `nxoff.NXoff.from_nexus`, `get_guide_params`, `_get_width_height` | Read geometry *back* out of NeXus; no consumer in the conversion path. |
| `path_navigator.NexusStructureNavigator` | A reader for navigating finished NeXus Structure JSON — a consumer-side convenience, not conversion. `nodes.find_child` / `nodes.get_attribute` cover what the tests need. Worth porting properly if users want it. |
| `Writer.to_json` | Wrote the structure to a file. Callers hold a plain dict and can `json.dump` it. |
| `nexus_structure.convert` — the `instr2ns` script | **Removed.** It translated an instrument niess did not build, which meant every target carried a second front-end forever. niess translates niess instruments; a `.instr` is not the source of truth in a niess world. `load_instr` survives for *reading* a file — see [Translate a McStas `.instr`](../how-to/translate-an-instr.md), which is the migration story this served. |

## Dependencies

`niess` never depended on `moreniius`, so there is nothing to remove from its
`pyproject.toml` — the dependency ran the other way, via `moreniius`'s
`[project.optional-dependencies] test = [..., 'niess', ...]`. Retiring `moreniius`
also retires its `nexusformat`, `networkx`, `zenlog` and `platformdirs` requirements;
`niess` already had `networkx` of its own and needs none of the others for this work.
