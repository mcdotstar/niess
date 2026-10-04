"""The documentation's examples are executable, and the pages really include them.

The README used to carry three code examples that had quietly stopped working: a
renamed keyword, a renamed component, and a class that emits an ``Arm`` rather than a
guide. Prose cannot be trusted to stay true on its own, so every example on the site
is a real module here, run by this test, asserting its own claims.

Two failure modes need covering, because they look different:

* an example stops working -- caught by running it;
* a page stops *including* the example -- ``pymdownx.snippets`` fails open on an
  unknown region, rendering an empty code block in a build that still succeeds, so the
  references are checked separately.
"""
import importlib.util
import re
from pathlib import Path

import pytest

from .optional_dependencies import (
    OPTIONAL_MODULES,
    missing_optional,
    skipping_missing_optionals,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
EXAMPLES = DOCS / 'examples'

# Mirrors pymdownx.snippets.base_path in zensical.toml
SNIPPET_BASE_PATHS = (EXAMPLES, ROOT)

# --8<-- "file.py"  or  --8<-- "file.py:region"
SNIPPET = re.compile(r'^\s*--8<--\s+"(?P<path>[^":]+)(?::(?P<region>[\w-]+))?"', re.M)


def example_paths():
    return sorted(EXAMPLES.glob('*.py'))


@pytest.mark.parametrize('path', example_paths(), ids=lambda p: p.stem)
def test_example_runs(path, tmp_path, monkeypatch):
    """Every example executes and its own assertions hold.

    An example resting on an extra -- `tof_model.py` on `tof` -- skips where the extra is
    not installed, and only for that reason: the skip is decided by which module the
    ImportError names, so an example broken any other way still fails here.
    """
    spec = importlib.util.spec_from_file_location(f'docs_example_{path.stem}', path)
    module = importlib.util.module_from_spec(spec)

    with skipping_missing_optionals():
        spec.loader.exec_module(module)

        assert hasattr(module, 'main'), f'{path.name} must define main(outdir)'
        monkeypatch.chdir(tmp_path)
        module.main(tmp_path)


def test_only_a_declared_extra_earns_a_skip():
    """The skip must not be able to swallow a real failure.

    It reads the module out of the ImportError, so an extra that is absent skips and
    anything else -- a typo in a niess import, a module that never existed -- still fails.
    Both are ImportErrors and only the declared name is excused.
    """
    absent = ModuleNotFoundError("No module named 'tof'", name='tof')
    assert missing_optional(absent) == 'tof'
    assert missing_optional(ModuleNotFoundError("No module named 'niess.toff'",
                                                name='niess.toff')) is None
    assert missing_optional(ValueError('nothing to do with imports')) is None


def test_the_extra_is_found_behind_a_helper_that_re_raises():
    """`niess.tof._tof()` replaces the ImportError with advice, losing `.name`.

    That is the shape the docs example actually fails in, so the chain has to be followed
    rather than only the exception that arrives.
    """
    try:
        try:
            raise ModuleNotFoundError("No module named 'tof'", name='tof')
        except ImportError as error:
            raise ImportError("niess.tof needs the 'tof' package") from error
    except ImportError as error:
        assert error.name is None
        assert missing_optional(error) == 'tof'


def test_the_extras_are_read_from_the_packaging():
    """A package that stops being optional stops being skippable, in the same commit."""
    assert 'tof' in OPTIONAL_MODULES
    assert 'scipp' not in OPTIONAL_MODULES, 'scipp is a hard dependency'


def test_the_changelog_names_the_version_being_released():
    """A release whose notes are headed by the previous version is worse than none.

    The changelog is included into the documentation site and copied into the GitHub
    release, so the number at its top is the one users will read as theirs. Nothing else
    checks that it moved when `__about__.py` did.
    """
    changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    latest = re.search(r'^## (\d+\.\d+\.\d+)', changelog, re.M)
    assert latest, 'the changelog has no released version'

    about = (ROOT / 'src' / 'niess' / '__about__.py').read_text(encoding='utf-8')
    version = re.search(r'__version__ = "([^"]+)"', about)
    assert latest.group(1) == version.group(1), (
        f'changelog is headed {latest.group(1)}, niess is {version.group(1)}'
    )


def test_there_are_examples_to_run():
    """Guard against the glob silently matching nothing."""
    assert example_paths(), f'no examples found in {EXAMPLES}'


def resolve_snippet(reference: str) -> Path | None:
    for base in SNIPPET_BASE_PATHS:
        candidate = base / reference
        if candidate.is_file():
            return candidate
    return None


def snippet_references():
    for markdown in sorted(DOCS.rglob('*.md')):
        for match in SNIPPET.finditer(markdown.read_text(encoding='utf-8')):
            yield markdown, match['path'], match['region']


def test_every_snippet_reference_resolves():
    """A page that includes a missing file or region renders an empty code block."""
    missing = []
    for markdown, reference, region in snippet_references():
        target = resolve_snippet(reference)
        if target is None:
            missing.append(f'{markdown.relative_to(ROOT)}: no such file {reference}')
            continue
        if region is None:
            continue
        text = target.read_text(encoding='utf-8')
        if f'[start:{region}]' not in text or f'[end:{region}]' not in text:
            missing.append(
                f'{markdown.relative_to(ROOT)}: {reference} has no region {region!r}'
            )

    assert not missing, 'broken snippet references:\n  ' + '\n  '.join(missing)


def test_every_example_region_is_used():
    """An unreferenced region is a sign a page dropped its include."""
    referenced = {(resolve_snippet(r), g) for _, r, g in snippet_references()}
    unused = []
    for path in example_paths():
        for region in re.findall(r'--8<--\s+\[start:([\w-]+)\]', path.read_text(encoding='utf-8')):
            if (path, region) not in referenced:
                unused.append(f'{path.name}:{region}')

    assert not unused, (
        'example regions that no page includes: ' + ', '.join(unused)
    )


def test_readme_quickstart_matches_the_tested_example():
    """GitHub cannot process snippet syntax, so the README duplicates the example.

    Asserting the duplicate is the next best thing: the README's three previous code
    blocks all rotted (a renamed keyword, a renamed reference, and a class that emits
    an Arm rather than a guide) precisely because nothing checked them.
    """
    import textwrap

    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    block = re.search(r'```python\n(.*?)```', readme, re.S)
    assert block, 'the README no longer has a python example'

    example = (EXAMPLES / 'quickstart.py').read_text(encoding='utf-8')
    region = example.split('# --8<-- [start:quickstart]\n')[1]
    region = region.split('    # --8<-- [end:quickstart]')[0]

    assert block.group(1).strip() == textwrap.dedent(region).strip()
