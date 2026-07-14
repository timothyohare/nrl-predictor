"""Every handler= string in the CDK stacks must resolve to a real module and function.

Guards against the failure documented in
docs/lessons/2026-07-14-missing-lambda-handlers.md: the weather and articles
scrapers were deployed for two months pointing at handler modules that were
never written, and only failed at invoke time.
"""
import importlib
import re
from pathlib import Path

import pytest

_INFRA = Path(__file__).parent.parent / "infra"


def _cdk_handlers() -> list[str]:
    handlers = []
    for stack in ("v1_stack.py", "v2_stack.py"):
        text = (_INFRA / stack).read_text()
        handlers.extend(m.group(1) for m in re.finditer(r'handler="([\w.]+)"', text))
    return handlers


_HANDLERS = _cdk_handlers()


def test_stacks_declare_handlers():
    assert len(_HANDLERS) >= 18


@pytest.mark.parametrize("handler", _HANDLERS)
def test_cdk_handler_path_resolves_to_callable(handler):
    module_path, func_name = handler.rsplit(".", 1)
    module = importlib.import_module(module_path)
    assert callable(getattr(module, func_name, None)), (
        f"CDK declares handler {handler!r} but {module_path} has no callable {func_name!r}"
    )
