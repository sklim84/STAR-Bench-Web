"""AML agent platform package.

``src.data`` and ``src.features`` are the tool layer: the DuckDB query
interface, the analysis and regulatory-reporting functions, and the agent
definition that STAR-Bench evaluates.  The Streamlit pages in ``app.py`` and
``_pages/`` are a separate consumer of that layer.

The tool modules decorate their query helpers with Streamlit's caching
decorators, which historically made Streamlit a hard import for anyone who only
wanted to *call the tools* -- benchmark runs, batch jobs, notebooks.  Requiring
a web-UI framework for that is a needless install, so when Streamlit is not
importable we register a minimal stand-in whose decorators return the wrapped
function unchanged.

This removes memoisation only.  Every decorated helper is a pure function of its
arguments, so results are identical either way; repeated identical queries are
simply re-executed.  When the real Streamlit is installed it is used untouched,
so the app itself is unaffected.

See ``requirements-tools.txt`` for the dependency set this makes possible.
"""

from __future__ import annotations

import sys
import types

__all__ = ["STREAMLIT_IS_STUBBED"]

STREAMLIT_IS_STUBBED = False


def _decorate(func):
    """Return ``func`` unchanged, plus the bits of Streamlit's cache API we use.

    Streamlit attaches ``.clear()`` to a cached function so callers can
    invalidate the cache; ``src/features/detector.py`` calls it after saving a
    retrained model.  With caching removed there is nothing to invalidate, so
    ``.clear()`` becomes a no-op.
    """
    if not hasattr(func, "clear"):
        func.clear = lambda *args, **kwargs: None
    return func


def _passthrough(*args, **kwargs):
    """Stand in for ``st.cache_data`` / ``st.cache_resource``.

    Supports the bare form (``@st.cache_resource``) and the called form
    (``@st.cache_data(ttl=300, hash_funcs=..., show_spinner=False)``); every
    keyword argument is accepted and ignored.
    """
    if len(args) == 1 and not kwargs and callable(args[0]):
        return _decorate(args[0])

    return _decorate


def _install_streamlit_stub() -> bool:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        pass
    else:
        return False

    stub = types.ModuleType("streamlit")
    stub.__doc__ = (
        "Minimal stand-in installed by src/__init__.py so the tool layer can be "
        "used without Streamlit. Install Streamlit to run the app itself."
    )
    stub.cache_data = _passthrough
    stub.cache_resource = _passthrough
    sys.modules["streamlit"] = stub
    return True


STREAMLIT_IS_STUBBED = _install_streamlit_stub()
