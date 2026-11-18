"""Optional dependency plumbing for the ``cryptography`` research extra.

AEGIS keeps a dependency-free core and moves every real cryptographic
primitive into the optional ``onion-lab`` extra. This module is the single
place that decides whether that extra is *absent* and whether it is *present
but unusable*, which are reported as different errors on purpose.

Importing a module that *contains* cryptographic code is always allowed: the
missing symbols are bound to placeholders instead of raising at import time, so
pure helpers (parsing, canonicalisation, validation, reporting) keep working
without the extra. Nothing here simulates cryptography -- a placeholder never
invents a key, a signature or ciphertext, it only fails loudly:

* :class:`MissingCryptoDependency` when the package is not installed;
* :class:`BrokenCryptoDependency` when the package is installed but its own
  import fails (missing shared library, half-written install, broken wheel).
  The original exception is preserved as ``__cause__`` instead of being
  swallowed and misreported as "not installed".

This module must stay dependency-free and must not import sibling ``anonlab``
modules; doing so would create import cycles.
"""
from __future__ import annotations

import functools
import importlib
import importlib.util
import inspect
import sys
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any, TypeVar

PACKAGE = "cryptography"
EXTRA = "onion-lab"
INSTALL_COMMAND = "python -m pip install 'rea-anon-lab[onion-lab]'"

__all__ = [
    "EXTRA",
    "INSTALL_COMMAND",
    "PACKAGE",
    "BrokenCryptoDependency",
    "MissingCryptoDependency",
    "MissingCryptographyError",
    "available",
    "import_fallback",
    "import_fallbacks",
    "import_module",
    "installed",
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


class BrokenCryptoDependency(RuntimeError):
    """Raised when ``cryptography`` is installed but cannot be imported.

    Distinct from :class:`MissingCryptoDependency` so a broken installation is
    never reported as a missing optional extra. The original import error is
    kept in :attr:`cause` and chained as ``__cause__``.
    """

    def __init__(self, feature: str, cause: BaseException | None = None) -> None:
        self.feature = feature
        self.cause = cause
        detail = f": {cause}" if cause is not None else ""
        super().__init__(
            f"{feature} requires the optional '{PACKAGE}' dependency, but it is "
            f"installed and failed to import{detail}. Reinstall it with: {INSTALL_COMMAND}"
        )


class MissingCryptographyError(Exception):
    """Placeholder for a missing ``cryptography`` exception class.

    Bound in ``except`` clauses of modules that import optional symbols. It is
    never raised, and matching it can never hide a real verification failure
    because the guarded code path cannot run without the dependency.
    """


def installed() -> bool:
    """Return True when a ``cryptography`` package is discoverable on disk.

    A discoverable package may still be broken; :func:`available` and the
    placeholders returned by :func:`missing_symbol` distinguish the two cases.
    """
    module = sys.modules.get(PACKAGE, ...)
    if module is None:
        # An explicit ``None`` entry means the import was blocked or rejected;
        # treat it as absent so callers get the install hint.
        return False
    try:
        return importlib.util.find_spec(PACKAGE) is not None
    except (ImportError, ValueError):  # pragma: no cover - unusable parent package
        return False


def available() -> bool:
    """Return True when real cryptographic primitives may be importable.

    A package that is installed but broken still reports True here: the guarded
    call then reaches the placeholder and raises :class:`BrokenCryptoDependency`
    with the original import error attached, which is the accurate diagnosis.
    """
    module = sys.modules.get(PACKAGE, ...)
    if module is not ...:
        return module is not None
    return installed()


def import_module(name: str, feature: str) -> ModuleType:
    """Import ``name``, preserving the difference between absent and broken."""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        if installed():
            raise BrokenCryptoDependency(feature, exc) from exc
        raise MissingCryptoDependency(feature) from exc


class _UnavailableSymbol:
    """Stand-in for a ``cryptography`` symbol that cannot be used."""

    __slots__ = ("_cause", "_feature", "_name")

    def __init__(self, name: str, feature: str, cause: BaseException | None = None) -> None:
        self._name = name
        self._feature = feature
        self._cause = cause

    def _fail(self) -> Any:
        if self._cause is None:
            raise MissingCryptoDependency(self._feature)
        raise BrokenCryptoDependency(self._feature, self._cause) from self._cause

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self._fail()

    def __getattr__(self, attribute: str) -> Any:
        self._fail()

    def __repr__(self) -> str:
        state = "broken" if self._cause is not None else "unavailable"
        return f"<{state} cryptography.{self._name} for {self._feature}>"


def missing_symbol(name: str, feature: str) -> Any:
    """Return a placeholder for ``cryptography`` symbol ``name``.

    Used as the ``except ImportError`` fallback so that a module containing
    both pure and cryptographic functionality stays importable without the
    optional extra, while any attempt to use the primitive raises
    :class:`MissingCryptoDependency` instead of degrading to a simulation.
    """
    return _UnavailableSymbol(name, feature)


def import_fallbacks(
    exc: ImportError,
    feature: str,
    names: Sequence[str],
    *,
    exception_names: Sequence[str] = (),
) -> tuple[Any, ...]:
    """Build the ``except ImportError`` fallbacks for one module import block.

    ``names`` are the module-level symbols in assignment order. Names listed in
    ``exception_names`` are exception classes and get the never-raised
    :class:`MissingCryptographyError` sentinel so ``except`` clauses stay valid.

    When the package is installed, every other name becomes a placeholder that
    raises :class:`BrokenCryptoDependency` chained to ``exc``. When it is
    absent, the placeholders raise :class:`MissingCryptoDependency`. In both
    cases the failure is reported at use time, so pure helpers in the same
    module keep working and no internal import error is swallowed.
    """
    broken = installed()
    fallbacks: list[Any] = []
    for name in names:
        if name in exception_names:
            fallbacks.append(MissingCryptographyError)
        elif broken:
            fallbacks.append(_UnavailableSymbol(name, feature, exc))
        else:
            fallbacks.append(_UnavailableSymbol(name, feature))
    return tuple(fallbacks)


def import_fallback(exc: ImportError, feature: str, name: str) -> Any:
    """Single-symbol convenience wrapper around :func:`import_fallbacks`."""
    return import_fallbacks(exc, feature, (name,))[0]


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
