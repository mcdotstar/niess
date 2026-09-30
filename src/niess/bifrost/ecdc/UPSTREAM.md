# ECDC stream bindings for BIFROST

`bindings.yaml` is a verbatim copy of the file of the same name in ECDC's
`bifrost-nexus-config` repository. ECDC compiles it, with its `instrument.yaml`, into
the NeXus template the real instrument's filewriter uses. It says which Kafka topic and
source fill each log.

| | |
|---|---|
| repository | `git@gitlab.esss.lu.se:ecdc/ess-nexus-configs/bifrost-nexus-config.git` |
| commit | `a8ede8573fe1c0b91b01c3d4232cd25da4a0c070` (2026-09-29) |

ECDC controls what the real file contains, so niess adopts their names rather than
mapping its own names onto theirs. Do not edit `bindings.yaml` here: a change belongs
upstream, and a local edit would be lost at the next refresh.

## Refreshing

```
cp <bifrost-nexus-config>/bindings.yaml src/niess/bifrost/ecdc/bindings.yaml
# update the commit above
python -m pytest tests/test_bifrost_ecdc_bindings.py
```

Each binding must either be used by niess or be listed, with a reason, in
`niess.bifrost.ecdc.NOT_SIMULATED`. The coverage test enforces this, so a binding that
ECDC adds or renames fails the test rather than going unnoticed.
