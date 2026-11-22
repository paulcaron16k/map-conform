"""The map-conform inline mapper.

Phase P0 ships a faithful pass-through: every Singer message, BATCH included, leaves exactly
as it arrived. Later phases replace the bodies of the ``map_*`` methods with the compiled
conform plan; the message plumbing stays.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from singer_sdk.exceptions import ConfigValidationError
from singer_sdk.helpers.capabilities import PluginCapabilities
from singer_sdk.mapper_base import InlineMapper
from singer_sdk.singerlib.encoding.base import SingerMessageType
from singer_sdk.singerlib.encoding.simple import Message

from map_conform.settings import Settings, parse_settings, settings_jsonschema
from map_conform.spec.errors import SpecError
from map_conform.spec.load import load_spec
from map_conform.spec.model import Spec, parse_spec

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import PurePath

    from singer_sdk.helpers.capabilities import CapabilitiesEnum


@dataclass(slots=True)
class PassThroughMessage(Message):
    """A message re-emitted unchanged, whatever its type.

    The SDK message classes rebuild a message from the fields they model, which drops the
    fields they do not (BATCH extensions, future spec additions) and re-serialises others,
    such as ``time_extracted``. A pass-through must do neither, so it keeps the decoded
    dictionary and serialises that.
    """

    payload: dict[str, Any] = field(default_factory=dict)
    """The message as decoded from the input line, ``type`` included."""

    def __post_init__(self) -> None:
        """Take the message type from the payload."""
        self.type = SingerMessageType(self.payload["type"])

    @override
    def to_dict(self) -> dict[str, Any]:
        """Return the message exactly as it was read.

        Returns:
            The decoded input message.
        """
        return self.payload


class MapConformMapper(InlineMapper):
    """Conform Singer streams so that targets receive clean data."""

    name = "map-conform"

    # Only what is implemented is advertised: ``stream-maps`` and ``flattening`` return with
    # the stream-map compatibility layer (WBS 12.x).
    capabilities: ClassVar[list[CapabilitiesEnum]] = [
        PluginCapabilities.ABOUT,
        PluginCapabilities.STRUCTURED_LOGGING,
    ]

    config_jsonschema = settings_jsonschema()

    def __init__(
        self,
        *,
        config: dict | PurePath | str | list[PurePath | str] | None = None,
        parse_env_config: bool = False,
        validate_config: bool = True,
    ) -> None:
        """Validate the settings and load the conform spec, failing before any data flows.

        Args:
            config: Plugin config: a dict, or one or more JSON file paths.
            parse_env_config: Also read settings from environment variables.
            validate_config: Validate the config against ``config_jsonschema``.

        Raises:
            ConfigValidationError: if the settings or the spec are invalid; every problem is
                listed with its path.
        """
        super().__init__(
            config=config,
            parse_env_config=parse_env_config,
            validate_config=validate_config,
        )
        try:
            self.settings: Settings = parse_settings(self.config)
            self.spec: Spec = self._load_spec(self.settings)
        except SpecError as exc:
            raise ConfigValidationError(
                f"Invalid {exc.source or 'configuration'}",
                errors=[str(issue) for issue in exc.issues],
            ) from exc

    def _load_spec(self, settings: Settings) -> Spec:
        if settings.spec_path is None and settings.spec is None:
            self.logger.info("No spec_path or spec set; conforming with the default rules.")
            return parse_spec({"version": 1}, "the default spec")
        spec = load_spec(settings.spec_path, settings.spec, settings.spec_vars)
        self.logger.info(
            "Loaded the conform spec from %s (%d stream rule(s)).",
            settings.spec_path or "the spec setting",
            len(spec.streams),
        )
        return spec

    @staticmethod
    def _pass_through(message_dict: dict[str, Any]) -> Iterator[PassThroughMessage]:
        yield PassThroughMessage(payload=message_dict)

    @override
    def map_schema_message(self, message_dict: dict) -> Iterator[PassThroughMessage]:
        """Pass a SCHEMA message through unchanged.

        Args:
            message_dict: A SCHEMA message JSON dictionary.

        Returns:
            The input message.
        """
        return self._pass_through(message_dict)

    @override
    def map_record_message(self, message_dict: dict) -> Iterator[PassThroughMessage]:
        """Pass a RECORD message through unchanged.

        Args:
            message_dict: A RECORD message JSON dictionary.

        Returns:
            The input message.
        """
        return self._pass_through(message_dict)

    @override
    def map_state_message(self, message_dict: dict) -> Iterator[PassThroughMessage]:
        """Pass a STATE message through unchanged.

        Args:
            message_dict: A STATE message JSON dictionary.

        Returns:
            The input message.
        """
        return self._pass_through(message_dict)

    @override
    def map_activate_version_message(
        self,
        message_dict: dict,
    ) -> Iterator[PassThroughMessage]:
        """Pass an ACTIVATE_VERSION message through unchanged.

        Args:
            message_dict: An ACTIVATE_VERSION message JSON dictionary.

        Returns:
            The input message.
        """
        return self._pass_through(message_dict)

    @override
    def map_batch_message(self, message_dict: dict) -> Iterator[PassThroughMessage]:
        """Pass a BATCH message through unchanged; its files are not opened.

        Args:
            message_dict: A BATCH message JSON dictionary.

        Returns:
            The input message.
        """
        return self._pass_through(message_dict)
