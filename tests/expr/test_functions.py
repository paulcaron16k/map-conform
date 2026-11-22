"""The function library (WBS 6.2)."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from map_conform.errors import StepFailed
from map_conform.expr import FUNCTIONS, Names, Row, compile_expr

UTC = dt.UTC


def call(text: str, **columns: object) -> object:
    """Evaluate with the given columns in scope."""
    row = Row.of({})
    row.values.update(columns)
    return compile_expr(text, Names(columns=frozenset(columns))).evaluate(row)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # predicates
        ("is_null(None), is_null(0)", (True, False)),
        ("is_string('a'), is_string(1)", (True, False)),
        ("is_number(1), is_number(1.5), is_number(d), is_number(True)", (True, True, True, False)),
        ("is_int(1), is_int(True), is_int(1.0)", (True, False, False)),
        ("is_decimal(d), is_bool(False), is_list([1]), is_dict({})", (True, True, True, True)),
        ("is_datetime(ts), is_date(ts), is_date(day)", (True, False, True)),
        ("is_blank(None), is_blank('  '), is_blank(' a ')", (True, True, False)),
        ("matches('^[0-9]{5}$', '12345'), matches('x', None)", (True, False)),
        # coercion
        ("to_int('12.0'), to_int(d0), to_int(None)", (12, 7, None)),
        ("to_float('1.5'), to_decimal('1.005', 10, 2)", (1.5, Decimal("1.01"))),
        ("to_bool('Yes'), to_bool('off'), to_bool(1)", (True, False, True)),
        ("to_str(d), to_str(True), to_str(day)", ("2.50", "true", "2026-03-14")),
        ("to_json({'a': d, 't': ts})", '{"a": 2.5, "t": "2026-03-14T09:26:53+00:00"}'),
        ("from_json('{\"a\": 1.10}')['a']", Decimal("1.10")),
        # temporal
        (
            "parse_datetime('03/14/2026 09:26', '%m/%d/%Y %H:%M', tz='America/New_York')",
            dt.datetime(2026, 3, 14, 9, 26, tzinfo=ZoneInfo("America/New_York")),
        ),
        (
            "ensure_utc('2026-03-14T10:26:53+01:00')",
            dt.datetime(2026, 3, 14, 9, 26, 53, tzinfo=UTC),
        ),
        ("ensure_utc(day)", dt.datetime(2026, 3, 14, tzinfo=UTC)),
        ("to_tz(ts, 'Asia/Tokyo').hour", 18),
        ("date_trunc(ts, 'month')", dt.datetime(2026, 3, 1, tzinfo=UTC)),
        ("date_trunc(ts, 'hour')", dt.datetime(2026, 3, 14, 9, tzinfo=UTC)),
        ("date_trunc(day, 'year')", dt.date(2026, 1, 1)),
        ("excel_date(46095.25)", dt.datetime(2026, 3, 14, 6)),  # noqa: DTZ001 -- serials are naive
        ("from_epoch(1773480413)", dt.datetime(2026, 3, 14, 9, 26, 53, tzinfo=UTC)),
        ("from_epoch(1773480413123, 'ms').microsecond", 123000),
        # text
        ("re_sub('[^0-9]', '', '(555) 123-4567')", "5551234567"),
        ("re_match('[A-Z]+', 'ABc'), re_match('x', 'y')", ("AB", None)),
        ("re_extract('id=(\\\\d+)', 'id=42;'), re_extract('\\\\d+', 'a7')", ("42", "7")),
        ("lower('Ab'), upper('Ab'), strip('xax', 'x')", ("ab", "AB", "a")),
        ("split('a,b', ','), join(['a', None, 'b'], '-')", (["a", "b"], "a-b")),
        ("pad_left(7, 3, '0'), len('abc')", ("007", 3)),
        # numeric
        ("round(2.5), round(-2.5), round(d, 1), round(1.25, 1)", (3, -3, Decimal("2.5"), 1.3)),
        ("floor(-1.5), ceil(1.2), abs(-2), clamp(15, 0, 10)", (-2, 2, 2, 10)),
        # misc
        ("coalesce(None, None, 3), nullif('N/A', 'N/A'), nullif(1, 2)", (3, None, 1)),
        ("md5('a')", "0cc175b9c0f1b6a831c399e269772661"),
        ("sha256('a')[:8]", "ca978112"),
        ("uuid5('dns', 'example.com')", "cfbff0d1-9375-5685-968c-48ce8b15ae17"),
        ("0 <= rand() < 1, 0 <= randint(5) < 5", (True, True)),
        # nulls pass through
        ("lower(None), to_decimal(None), ensure_utc(None), re_sub('a', 'b', None)", (None,) * 4),
    ],
)
def test_functions(text: str, expected: object) -> None:
    """Each function on typical values and on null."""
    columns = {
        "d": Decimal("2.50"),
        "d0": Decimal("7.0"),
        "ts": dt.datetime(2026, 3, 14, 9, 26, 53, tzinfo=UTC),
        "day": dt.date(2026, 3, 14),
    }
    assert call(text, **columns) == expected


def test_uuid4_is_random() -> None:
    """uuid4 returns a fresh version-4 UUID."""
    first, second = call("uuid4()"), call("uuid4()")
    assert first != second
    assert uuid.UUID(str(first)).version == 4  # noqa: PLR2004


def test_now_utc_is_aware() -> None:
    """now_utc is in UTC."""
    assert call("now_utc().tzinfo") is UTC


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("to_int('1.5')", "has a fraction"),
        ("to_int(True)", "a boolean is not a number"),
        ("to_bool('maybe')", "is not a boolean"),
        ("to_decimal('123.4', 3, 1)", "more than 3 digits"),
        ("from_json('{')", "not JSON"),
        ("date_trunc(ts, 'week')", "unit must be one of"),
        ("from_epoch(1, 'days')", "unit must be"),
        ("join('ab')", "join needs a list"),
    ],
)
def test_function_errors(text: str, message: str) -> None:
    """Bad input is a StepFailed with a reason."""
    with pytest.raises(StepFailed, match=message):
        call(text, ts=dt.datetime(2026, 3, 14, tzinfo=UTC))


def test_every_function_is_documented() -> None:
    """map-conform functions lists a signature and a one-line doc for each."""
    for function in FUNCTIONS.values():
        assert function.doc, function.name
        assert re.match(rf"{function.name}[(.]", function.signature), function.signature


def test_design_function_table_is_covered() -> None:
    """Every function the detailed design lists (§7) exists; fake arrives with faker."""
    listed = (
        "is_null is_string is_number is_int is_decimal is_bool is_datetime is_date is_list "
        "is_dict is_blank matches to_int to_float to_decimal to_bool to_str to_json from_json "
        "parse_datetime ensure_utc to_tz now_utc date_trunc excel_date from_epoch re_sub "
        "re_match re_extract lower upper strip split join len pad_left round abs min max floor "
        "ceil clamp coalesce nullif md5 sha256 uuid4 uuid5 datetime decimal math re"
    )
    names = set(listed.split())
    assert names <= set(FUNCTIONS)
