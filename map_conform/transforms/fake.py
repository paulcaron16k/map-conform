"""Fake data: the ``fake`` step and the ``fake`` object in expressions (WBS 12.4).

Both need the ``faker`` extra (``pip install map-conform[faker]``). ``defaults.faker`` sets
the seed and locale, the same as the SDK's ``faker_config``: with a seed, ``Faker.seed`` is
called before the generator is created, exactly as the SDK does, so seeded runs give the same
values in the same order, and the same values the SDK mapper gives.

The generator is created on first use, so a stream that never fakes anything never imports
Faker. In expressions, ``fake`` is a sandbox proxy: provider methods (``fake.email()``) and
``fake.seed_instance(value)`` are allowed; private names, ``seed`` (global seeding) and
``add_provider`` are not.
"""

from __future__ import annotations

import functools
import importlib.util
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from map_conform.errors import StepFailed
from map_conform.expr.sandbox import Proxy, SandboxError
from map_conform.spec._struct import documented
from map_conform.transforms.registry import ANY, Registry, Transform

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from map_conform.spec.model import FakerDefaults
    from map_conform.transforms.registry import Context

NEEDS_EXTRA = "fake needs the faker extra: pip install 'map-conform[faker]'"
_DENIED = frozenset({"seed", "add_provider", "seed_locale", "factories", "random"})


def available() -> bool:
    """Whether Faker is installed."""
    return importlib.util.find_spec("faker") is not None


class FakeData(Proxy):
    """A lazily created, seeded Faker generator."""

    __slots__ = ("_faker", "_locale", "_seed")

    def __init__(
        self, seed: int | None = None, locale: str | tuple[str, ...] | None = None
    ) -> None:
        """Remember the settings; Faker is imported on first use."""
        self._seed = seed
        self._locale = locale
        self._faker: Any = None

    @classmethod
    def from_settings(cls, settings: FakerDefaults) -> FakeData:
        """From ``defaults.faker``."""
        return cls(settings.seed, settings.locale)

    def generator(self) -> Any:  # noqa: ANN401 -- a faker.Faker
        """The Faker instance, created (and seeded) on first use.

        Raises:
            SandboxError: when Faker is not installed.
        """
        if self._faker is None:
            if not available():
                raise SandboxError(NEEDS_EXTRA)
            from faker import Faker  # noqa: PLC0415 -- optional dependency

            if self._seed is not None:
                Faker.seed(self._seed)  # as the SDK seeds, for the same values
            locale = list(self._locale) if isinstance(self._locale, tuple) else self._locale
            self._faker = Faker(locale) if locale is not None else Faker()
        return self._faker

    @override
    def attribute(self, name: str) -> object:
        """A provider method or ``seed_instance``.

        Raises:
            SandboxError: for private and global-state names.
        """
        if name.startswith("_") or name in _DENIED:
            msg = f"fake.{name} is not available in expressions"
            raise SandboxError(msg)
        return getattr(self.generator(), name)

    @override
    def __repr__(self) -> str:
        """``<fake seed=1 locale=en_US>``."""
        return f"<fake seed={self._seed} locale={self._locale}>"


@functools.cache
def _providers(locale: str | None) -> frozenset[str]:
    from faker import Faker  # noqa: PLC0415 -- optional dependency

    fake = Faker(locale) if locale else Faker()
    return frozenset(name for name in dir(fake) if not name.startswith("_"))


def _provider_problem(provider: str) -> str | None:
    if not available():
        return NEEDS_EXTRA
    if provider.startswith("_") or provider in _DENIED or provider not in _providers(None):
        return f"{provider!r} is not a Faker provider"
    return None


@dataclass(frozen=True)
class FakeKwargs:
    """fake options."""

    provider: str = documented(
        "A Faker provider, e.g. name, email, credit_card_number.",
        metadata={"check": _provider_problem},
    )
    args: tuple[Any, ...] = documented("Positional arguments for the provider.", default=())
    unique: bool = documented("Never repeat a value within the run.", default=False)


def _fake(_value: object, k: FakeKwargs, ctx: Context) -> object:
    if ctx.fake is None:
        raise StepFailed("fake is not available here")
    try:
        generator = ctx.fake.generator()
        source = generator.unique if k.unique else generator
        return getattr(source, k.provider)(*k.args)
    except SandboxError as exc:
        raise StepFailed(str(exc)) from None
    except Exception as exc:  # noqa: BLE001 -- e.g. Faker's UniquenessException
        raise StepFailed(f"{type(exc).__name__}: {exc}") from None


def register(registry: Registry) -> None:
    """Add the fake step."""
    registry.register(
        Transform(
            "fake",
            _fake,
            kwargs=FakeKwargs,
            positional="provider",
            accepts=frozenset({ANY}),
            produces=lambda _stage, _k: None,
        )
    )
