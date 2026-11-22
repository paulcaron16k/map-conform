"""The map-conform inline mapper.

At SCHEMA the mapper compiles a plan for each output stream of the tap stream; each RECORD is
conformed by the row executor. STATE passes through in order; ACTIVATE_VERSION is renamed to
the output streams. BATCH is conformed from phase P4 (WBS 8.x).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from singer_sdk.exceptions import ConfigValidationError
from singer_sdk.helpers.capabilities import PluginCapabilities
from singer_sdk.mapper_base import InlineMapper
from singer_sdk.singerlib.encoding.base import SingerMessageType
from singer_sdk.singerlib.encoding.simple import Message

from map_conform.errors import RowRejected, ThresholdExceeded
from map_conform.metadata import Metadata, sdc_schema
from map_conform.metrics import StreamMetrics, write_metrics
from map_conform.plan.compile import compile_stream
from map_conform.plan.row import RowExecutor
from map_conform.rejects import RejectSink
from map_conform.settings import Settings, parse_settings, settings_jsonschema
from map_conform.spec.errors import SpecError
from map_conform.spec.load import load_spec, output_streams
from map_conform.spec.model import Defaults, Spec, parse_spec
from map_conform.transforms.builtins import builtin_registry
from map_conform.udfs import load_udfs, registry_with

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import PurePath

    from singer_sdk.helpers.capabilities import CapabilitiesEnum


@dataclass(slots=True)
class RawMessage(Message):
    """A message written exactly as given.

    The SDK message classes rebuild a message from the fields they model, which drops the
    fields they do not and re-serialises others, such as ``time_extracted``. The mapper
    builds the output dictionary itself and serialises that.
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
        self._started = dt.datetime.now(tz=dt.UTC)
        self._metadata = Metadata(self._started)
        self._executors: dict[str, list[RowExecutor]] = {}
        self._rows: dict[str, int] = {}
        self._metrics: dict[str, StreamMetrics] = {}
        self._limits: dict[str, Defaults] = {}
        self._rejects: RejectSink | None = None
        try:
            self.settings: Settings = parse_settings(self.config)
            self.spec: Spec = self._load_spec(self.settings)
            udfs = load_udfs(self.spec.udfs, allow_python_udfs=self.settings.allow_python_udfs)
            self.registry = registry_with(builtin_registry(), udfs)
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

    # --- message handling ---------------------------------------------------------------

    def _outputs(self, tap_stream: str) -> list[RowExecutor]:
        executors = self._executors.get(tap_stream)
        if executors is None:
            msg = f"RECORD for stream {tap_stream!r} before its SCHEMA"
            raise ValueError(msg)
        return executors

    @override
    def map_schema_message(self, message_dict: dict) -> Iterator[RawMessage]:
        """Compile a plan for each output stream and emit its conformed SCHEMA.

        Args:
            message_dict: A SCHEMA message JSON dictionary.

        Yields:
            One conformed SCHEMA per output stream (none for a dropped stream).

        Raises:
            ConfigValidationError: if a plan does not compile; every problem has its path.
        """
        tap_stream = message_dict["stream"]
        executors: list[RowExecutor] = []
        for resolved in output_streams(self.spec, tap_stream):
            try:
                plan = compile_stream(
                    self.spec,
                    resolved,
                    message_dict["schema"],
                    self.registry,
                    key_properties=tuple(message_dict.get("key_properties") or ()),
                    bookmark_properties=tuple(message_dict.get("bookmark_properties") or ()),
                    strict=self.settings.strict,
                    config=self.settings.spec_vars,
                )
            except SpecError as exc:
                raise ConfigValidationError(
                    f"Invalid {exc.source}", errors=[str(i) for i in exc.issues]
                ) from exc
            for note in plan.notes:
                self.logger.info("Stream %r: %s", tap_stream, note)
            metadata = self._metadata if resolved.settings.metadata == "sdc" else None
            metrics = self._metrics.setdefault(plan.name, StreamMetrics())
            self._limits[plan.name] = resolved.settings
            executors.append(RowExecutor(plan, resolved.settings, metadata, metrics))
            schema = dict(plan.schema)
            if metadata is not None:
                schema["properties"] = {**schema["properties"], **sdc_schema()}
            out: dict[str, Any] = {
                "type": "SCHEMA",
                "stream": plan.name,
                "schema": schema,
                "key_properties": list(plan.key_properties),
            }
            if plan.bookmark_properties:
                out["bookmark_properties"] = list(plan.bookmark_properties)
            yield RawMessage(payload=out)
        if not executors:
            self.logger.info("Stream %r is dropped by the spec.", tap_stream)
        self._executors[tap_stream] = executors

    @override
    def map_record_message(self, message_dict: dict) -> Iterator[RawMessage]:
        """Conform the record for each output stream.

        Args:
            message_dict: A RECORD message JSON dictionary.

        Yields:
            One conformed RECORD per output stream; ``version`` and ``time_extracted`` are
            preserved.
        """
        tap_stream = message_dict["stream"]
        row = self._rows[tap_stream] = self._rows.get(tap_stream, 0) + 1
        for executor in self._outputs(tap_stream):
            try:
                record = executor.run(message_dict["record"], message_dict, row)
            except RowRejected as rejected:
                self._reject(executor, rejected, message_dict["record"])
                continue
            if record is None:  # dropped by the stream's filter
                continue
            executor.metrics.rows_out += 1
            out: dict[str, Any] = {"type": "RECORD", "stream": executor.plan.name, "record": record}
            for passed in ("version", "time_extracted"):
                if passed in message_dict:
                    out[passed] = message_dict[passed]
            yield RawMessage(payload=out)

    def _reject(self, executor: RowExecutor, rejected: RowRejected, record: dict[str, Any]) -> None:
        executor.metrics.rows_rejected += 1
        if self._rejects is None:
            storage = Path(self.settings.reject.storage)
            run_id = self._started.strftime("%Y%m%dT%H%M%S%fZ")
            self._rejects = RejectSink(storage, self.settings.reject.format, run_id)
        self._rejects.write(executor.plan.name, rejected.error, record)
        self.logger.warning("Rejected: %s", rejected.error)

    def _close_rejects(self) -> None:
        if self._rejects is None:
            return
        self._rejects.close()
        for stream, path in self._rejects.paths.items():
            self.logger.warning("Rejected rows of %r are in %s", stream, path)

    def _check_thresholds(self) -> None:
        """Fail when a stream's reject or null rate is over its limit.

        Raises:
            ThresholdExceeded: naming the stream, the rate and the limit.
        """
        for stream, metrics in self._metrics.items():
            limits = self._limits[stream]
            for label, count, limit in (
                ("rejected", metrics.rows_rejected, limits.max_reject_rate),
                ("nulled", metrics.rows_nulled, limits.max_null_rate),
            ):
                if limit is not None and metrics.rate(count) > limit:
                    raise ThresholdExceeded(
                        stream,
                        what=label,
                        rate=metrics.rate(count),
                        limit=limit,
                        count=count,
                        rows=metrics.rows_in,
                    )

    @override
    def map_state_message(self, message_dict: dict) -> Iterator[RawMessage]:
        """Pass STATE through unchanged, in order.

        Args:
            message_dict: A STATE message JSON dictionary.

        Yields:
            The input message, after the rate thresholds are checked, so a target never
            commits a bookmark past rows a bad source spoiled.
        """
        try:
            self._check_thresholds()
        except ThresholdExceeded:
            self._close_rejects()
            raise
        yield RawMessage(payload=message_dict)

    @override
    def process_endofpipe(self) -> None:
        """Check thresholds, close the reject sink, and report metrics."""
        try:
            self._check_thresholds()
        finally:
            self._close_rejects()
            for stream, metrics in sorted(self._metrics.items()):
                self.logger.info("Metrics for %r: %s", stream, json.dumps(metrics.to_dict()))
            if self.settings.metrics_path:
                write_metrics(self.settings.metrics_path, self._metrics)

    @override
    def map_activate_version_message(self, message_dict: dict) -> Iterator[RawMessage]:
        """Emit ACTIVATE_VERSION for each output stream of the tap stream.

        Args:
            message_dict: An ACTIVATE_VERSION message JSON dictionary.

        Yields:
            The message, renamed to each output stream.
        """
        for executor in self._executors.get(message_dict["stream"], []):
            yield RawMessage(payload={**message_dict, "stream": executor.plan.name})

    @override
    def map_batch_message(self, message_dict: dict) -> Iterator[RawMessage]:
        """Refuse BATCH until the columnar engine exists (WBS 8.x).

        Passing BATCH files through unconformed would contradict the conformed SCHEMA.

        Args:
            message_dict: A BATCH message JSON dictionary.

        Raises:
            NotImplementedError: always, for now.
        """
        msg = (
            f"BATCH messages (stream {message_dict.get('stream')!r}) are conformed from phase "
            "P4 (WBS 8.x). Until then, run the tap without BATCH output."
        )
        raise NotImplementedError(msg)
