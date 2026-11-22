"""The map-conform inline mapper.

Phase P0 ships a faithful pass-through: every Singer message, BATCH included, leaves exactly
as it arrived. Later phases replace the bodies of the ``map_*`` methods with the compiled
conform plan; the message plumbing stays.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

import singer_sdk.typing as th
from singer_sdk.helpers.capabilities import PluginCapabilities
from singer_sdk.mapper_base import InlineMapper
from singer_sdk.singerlib.encoding.base import SingerMessageType
from singer_sdk.singerlib.encoding.simple import Message

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterator

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

    # Settings arrive with the spec loader (WBS 2.4).
    config_jsonschema = th.PropertiesList().to_dict()

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
