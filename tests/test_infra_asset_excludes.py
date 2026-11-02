"""The v1/v2 Lambda code assets must never ship dotfiles.

Both stacks package the repo root, and the repo-root `.env` holds the local
Anthropic / Tavily / odds API keys. Until 2026-10-28 neither `_ASSET_EXCLUDE`
excluded hidden files, so `.env` (and ~38 MB of `.mypy_cache`) was zipped into
every deployed NRL Lambda. The Lambdas read their keys from Secrets Manager, so
nothing at runtime needs `.env`.

Checked with CDK's own `GlobIgnoreStrategy` — the matcher `Code.from_asset`
applies — over a planted tree, so this proves the patterns behave, not just
that a string is in a list. A full synth would need Docker bundling.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import aws_cdk as cdk
import pytest

_INFRA = Path(__file__).parent.parent / "infra"

_PLANTED_SECRETS = [".env", ".env.local", "common/.env", "scrapers/nrl/.env", ".mypy_cache/x.json"]
_PLANTED_SOURCE = ["common/teams.py", "scrapers/nrl/draw.py", "pyproject.toml"]


def _asset_exclude(stack_file: str) -> list[str]:
    spec = importlib.util.spec_from_file_location(f"_excl_{stack_file}", _INFRA / stack_file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module._ASSET_EXCLUDE)


def _shipped(root: Path, patterns: list[str]) -> set[str]:
    """Files CDK would include: walk the tree, pruning ignored directories."""
    strategy = cdk.GlobIgnoreStrategy(str(root), patterns)
    shipped: set[str] = set()

    def walk(directory: Path) -> None:
        for path in directory.iterdir():
            if strategy.ignores(str(path)):
                continue
            if path.is_dir():
                walk(path)
            else:
                shipped.add(path.relative_to(root).as_posix())

    walk(root)
    return shipped


@pytest.fixture
def planted_tree(tmp_path: Path) -> Path:
    for rel in _PLANTED_SECRETS + _PLANTED_SOURCE:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    return tmp_path


@pytest.mark.parametrize("stack_file", ["v1_stack.py", "v2_stack.py"])
def test_asset_never_ships_dotfiles(stack_file, planted_tree):
    shipped = _shipped(planted_tree, _asset_exclude(stack_file))
    leaked = sorted(rel for rel in _PLANTED_SECRETS if rel in shipped)
    assert leaked == [], f"{stack_file} asset would ship {leaked}"


@pytest.mark.parametrize("stack_file", ["v1_stack.py", "v2_stack.py"])
def test_asset_still_ships_ordinary_source(stack_file, planted_tree):
    shipped = _shipped(planted_tree, _asset_exclude(stack_file))
    assert set(_PLANTED_SOURCE) <= shipped
