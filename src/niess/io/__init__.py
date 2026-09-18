"""Serialising niess objects, and reading McCode's.

Deliberately empty of imports. `io/utils.py` imports `niess.bifrost` at module level to
register two friendly names in its encoding table, and `niess.components.source` reaches
back into `niess.io.mccode`; the only thing keeping that from being a cycle is that
importing `niess.io` pulls in nothing at all. Name the module you want:

    from niess.io.json import to_json, from_json
    from niess.io.mccode import load_instr
"""
