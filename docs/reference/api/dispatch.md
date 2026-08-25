# niess.dispatch

The registry mechanism every conversion target shares: three-tier resolution keyed on
niess provenance or the McStas component type, for a live niess object or for an
assembled instance.

`niess.provenance` is the record it resolves against — written onto every emitted McStas
component, and read back by whatever has only the emitted file.

::: niess.dispatch

::: niess.provenance
