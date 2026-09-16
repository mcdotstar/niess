# Command line

## `niess-scaffold`

Generate a first-draft niess submodule from a McStas `.instr` file.

```console
$ niess-scaffold my_instrument.instr -o src/niess --origin sample
```

| option | |
| --- | --- |
| `instr` | the `.instr` file to convert |
| `-o`, `--output` | directory to write the module into (default: `.`) |
| `--origin` | the component everything is measured against, usually the sample position |
| `--section` | name for the generated `Section` class (default: `Primary`) |
| `--report-only` | print what would be converted, and write nothing |
| `--no-verify` | skip the placement check |

It prints a report — what was mapped, what is still `Opaque`, which parameters were
frozen — and then checks that the module it is about to write places every component
where the `.instr` does. **If that check fails it writes nothing and exits non-zero**,
because a module that describes a different instrument is worse than no module.

One way, best-effort and lossy by design. What it produces is a starting point; see
[Translate a McStas `.instr`](../how-to/translate-an-instr.md) for what to do with it and
what it deliberately leaves alone.

This is a developer tool. Nothing in `niess` imports `niess.scaffold` at run time, and a
generated module does not depend on it — except for `test_placement.py`, which uses
`niess.scaffold.verify.compare`.
