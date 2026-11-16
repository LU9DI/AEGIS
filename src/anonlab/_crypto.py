"""Optional dependency plumbing for the ``cryptography`` research extra.

AEGIS keeps a dependency-free core and moves every real cryptographic
primitive into the optional ``onion-lab`` extra. This module is the single
place that decides whether that extra is present.

Importing a module that *contains* cryptographic code is always allowed: the
missing symbols are bound to :class:`_UnavailableSymbol` placeholders instead
of raising at import time, so pure helpers (parsing, canonicalisation,
validation, reporting) keep working without the extra. Nothing here simulates
cryptography -- a placeholder never invents a key, a signature or ciphertext,
it only fails loudly through :class:`MissingCryptoDependency`.

This module must stay dependency-free and must not import sibling ``anonlab``
modules; doing so would create import cycles.
"""
from __future__ import annotations

import functools
import importlib
import importlib.util
import inspect
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any, TypeVar

PACKAGE = "cryptography"
EXTRA = "onion-lab"
INSTALL_COMMAND = "python -m pip install 'rea-anon-lab[onion-lab]'"

__all__ = [
    "EXTRA",
    "INSTALL_COMMAND",
    "PACKAGE",
    "MissingCryptoDependency",
    "MissingCryptographyError",
    "available",
    "import_module",
    "missing_symbol",
    "requires_crypto",
]

_F = TypeVar("_F", bound=Callable[..., Any])


class MissingCryptoDependency(RuntimeError):
    """Raised when an operation needs real cryptography that is not installed.

    This is a ``RuntimeError`` subclass so existing callers that already handle
    ``RuntimeError`` from the previous import-time guard keep working.
    """

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(
            f"{feature} requires the optional '{PACKAGE}' dependency; "
            f"install it with: {INSTALL_COMMAND}"
        )


class MissingCryptographyError(Exception):
    """Placeholder for a missing ``cryptography`` exception class.

    Bound in ``except`` clauses of modules that import optional symbols. It is
    never raised, and matching it can never hide a real verification failure
    because the guarded code path cannot run without the dependency.
    """


def available() -> bool:
    """Return True when the real ``cryptography`` package can be imported."""
    module = sys.modules.get(PACKAGE, ...)
    if module is not ...:
        # A ``None`` entry is how a failed import is remembered.
        return module is not None
    try:
        return importlib.util.find_spec(PACKAGE) is not None
    except (ImportError, ValueError):  # pragma: no cover - broken parent package
        return False


def import_module(name: str, feature: str) -> ModuleType:
    """Import ``name`` or raise :class:`MissingCryptoDependency`."""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise MissingCryptoDependency(feature) from exc


class _UnavailableSymbol:
    """Stand-in for a missing ``cryptography`` symbol that fails on use."""

    __slots__ = ("_feature", "_name")

    def __init__(self, name: str, feature: str) -> None:
        self._name = name
        self._feature = feature

    def _fail(self) -> Any:
        raise MissingCryptoDependency(self._feature)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self._fail()

    def __getattr__(self, attribute: str) -> Any:
        self._fail()

    def __repr__(self) -> str:
        return f"<unavailable cryptography.{self._name} for {self._feature}>"


def missing_symbol(name: str, feature: str) -> Any:
    """Return a placeholder for ``cryptography`` symbol ``name``.

    Used as the ``except ImportError`` fallback so that a module containing
    both pure and cryptographic functionality stays importable without the
    optional extra, while any attempt to use the primitive raises
    :class:`MissingCryptoDependency` instead of degrading to a simulation.
    """
    return _UnavailableSymbol(name, feature)


def _guard(target: _F, feature: str) -> _F:
    if inspect.iscoroutinefunction(target):

        @functools.wraps(target)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not available():
                raise MissingCryptoDependency(feature)
            return await target(*args, **kwargs)

        wrapper: Any = async_wrapper
    else:

        @functools.wraps(target)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not available():
                raise MissingCryptoDependency(feature)
            return target(*args, **kwargs)

        wrapper = sync_wrapper

    try:
        wrapper.__signature__ = inspect.signature(target)
    except (TypeError, ValueError):  # pragma: no cover - exotic callables
        pass
    return wrapper  # type: ignore[no-any-return]


def requires_crypto(feature: str) -> Callable[[_F], _F]:
    """Decorate a function or method that needs real cryptographic primitives.

    The wrapper preserves the wrapped callable's name, qualified name, module,
    docstring, annotations, ``__dict__`` and call signature, and it only ever
    raises :class:`MissingCryptoDependency` *before* delegating. Exceptions
    raised by the wrapped callable itself propagate unchanged.

    Works on plain functions, instance methods, ``staticmethod`` and
    ``classmethod`` objects (the latter two are re-wrapped in their original
    descriptor type), so a guarded method keeps its normal binding behaviour.
    Coroutine functions stay coroutine functions: the guard runs before the
    first ``await`` instead of turning the callable into a synchronous one.
    """

    def decorate(target: _F) -> _F:
        if isinstance(target, (staticmethod, classmethod)):
            return type(target)(_guard(target.__func__, feature))  # type: ignore[return-value]
        return _guard(target, feature)

    return decorate
