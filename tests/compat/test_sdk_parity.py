"""The SDK's own stream-map test cases give the SDK's output through map-conform (WBS 12.9).

Every case from the Singer SDK's ``tests/core/test_mapper.py`` (except the BATCH one, which
waits for P4) runs through the SDK's ``PluginMapper`` and through the map-conform mapper,
given the same SCHEMA and RECORD messages and the same settings. Stream names, key
properties, column names, the type family of each column and every value must agree, up to
the deliberate differences listed in :mod:`tests.compat.compare`.
"""

from __future__ import annotations

import pytest

from tests.compat.compare import comparable_sdk_record, family, normal, sdk_name
from tests.compat.harness import ours_run, sdk_run
from tests.compat.sdk_cases import CASES


@pytest.mark.parametrize("case", list(CASES))
def test_sdk_case(case: str) -> None:
    """One SDK test case: the same streams, keys, columns, types and values."""
    streams, stream_maps, config = CASES[case]
    expected = sdk_run(streams, stream_maps, config)
    actual = ours_run(streams, stream_maps, config)

    assert [(m[0], m[1]) for m in actual] == [(m[0], m[1]) for m in expected]
    sdk_schemas = {m[1]: m for m in expected if m[0] == "SCHEMA"}
    our_schemas = {m[1]: m for m in actual if m[0] == "SCHEMA"}
    for stream, (_, _, schema, keys) in sdk_schemas.items():
        ours = our_schemas[stream][2]["properties"]
        assert our_schemas[stream][3] == [sdk_name(k) for k in keys]
        expected_types = {sdk_name(k): family(v) for k, v in schema["properties"].items()}
        assert {k: family(v) for k, v in ours.items()} == expected_types

    for sdk, ours in zip(
        (m for m in expected if m[0] == "RECORD"),
        (m for m in actual if m[0] == "RECORD"),
        strict=True,
    ):
        columns = list(our_schemas[ours[1]][2]["properties"])
        assert normal(ours[2]) == comparable_sdk_record(sdk[2], columns), (sdk[2], ours[2])


def test_every_sdk_case_is_ported() -> None:
    """The SDK's test_mapped_stream ids, minus BATCH, plus its four other mapper tests."""
    assert len(CASES) == 38  # noqa: PLR2004 -- 34 + 4
    assert "aliased_stream_batch" not in CASES
