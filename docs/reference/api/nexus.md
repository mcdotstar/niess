# niess.nexus

ESS NeXus Structure JSON, read off the niess object tree. See
[Produce NeXus Structure JSON](../../how-to/nexus-structure.md) for the task-oriented
guide and [Write NeXus translators](../../how-to/custom-nexus-registry.md) for extending
it.

Converting an instrument niess did not build reads the emitted McStas instead, which is
`niess.nexus.via_instr` — the older of the two routes, deliberately undocumented here
because it is what goes when reading a foreign `.instr` stops being served.

::: niess.nexus

::: niess.nexus.bifrost
