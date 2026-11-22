"""SDK stream-map expressions evaluate exactly as the SDK evaluates them (WBS 6.1 acceptance).

The corpus is every expression in the Singer SDK's own mapper tests
(``tests/core/test_mapper.py``), plus the common idioms of its documentation. Each one is
evaluated twice on the same record: by the SDK's simpleeval evaluator, with the SDK's names and
functions, and by map-conform after the SDK rewrite (bare record names become
``record['...']``). The results must be equal.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from typing import Any

import pytest
import simpleeval
from singer_sdk.mapper import CustomStreamMap

from map_conform.expr import Names, Row, compile_expr
from map_conform.expr.sdk import rewrite_sdk_expression

REPOSITORY = {
    "name": "tap-something",
    "owner_email": "sample1@example.com",
    "description": "Comment A",
    "create_date": "2019-01-01",
}
USER = {
    "email": "alice@example.com",
    "count": 21,
    "user": {"id": 1, "sub": {"num": 1}, "some_numbers": [3.14, 2.718]},
    "joined_at": "2022-01-01T00:00:00Z",
    "items": [1, 2, 3],
}
CONFIG = {"hash_seed": "super_secret_hash_seed", "some_date_string": "2024-10-10T10:10:10Z"}

CORPUS: list[tuple[str, dict[str, Any]]] = [
    # tests/core/test_mapper.py
    ("_['name']", REPOSITORY),
    ("owner_email.split('@')[1]", REPOSITORY),
    ("md5(config['hash_seed'] + owner_email)", REPOSITORY),
    ("'[masked]'", REPOSITORY),
    ("str('[masked]')", REPOSITORY),
    ("int(datetime.date.fromisoformat(create_date).year)", REPOSITORY),
    ("int('0')", REPOSITORY),
    ("'tap-' in name or 'target-' in name", REPOSITORY),
    ("'database'", REPOSITORY),
    ("md5(email)", USER),
    ("sha256(email)", USER),
    ("int(count-1)", USER),
    ("'aliased_' + __stream_name__", USER),
    ("__stream_name__.upper()", USER),
    ("__stream_name__", USER),
    ("__original_stream_name__", USER),
    ("self.upper()", USER),
    ("_['email'].upper()", USER),
    ("count", USER),
    ("record", USER),
    ("datetime.datetime.fromisoformat(joined_at).date()", USER),
    ("float(datetime.datetime.fromisoformat(joined_at).timestamp())", USER),
    ("datetime.datetime.fromisoformat(config['some_date_string'])", USER),
    ("json.dumps(user, default=str)", USER),
    ("count < 20", USER),
    ("bool(count < 20)", USER),
    # documented idioms
    ("email.split('@')[0] if email else None", USER),
    ("email.lower().replace('example', 'masked')", USER),
    ("[x * 2 for x in items if x > 1]", USER),
    ("{k: v for k, v in record.items() if k != 'user'}", USER),
    ("user['sub']['num'] + 1", USER),
    ("user.get('missing', 'default')", USER),
    ("items[0] < items[-1] and count >= 21", USER),
    ("str(count) + '-' + email[:5]", USER),
    ("float(count) / 4", USER),
    ("None if count > 100 else count * 2", USER),
    ("items[-1] - items[0]", USER),
    ("json.loads(json.dumps(user))['id']", USER),
    ("datetime.datetime(2024, 1, 1).isoformat()", USER),
    ("datetime.date.fromisoformat(joined_at[:10]).isoformat()", USER),
]


def sdk_eval(text: str, record: dict[str, Any], property_name: str) -> object:
    """Evaluate exactly as singer_sdk.mapper.CustomStreamMap._eval does."""
    mapper = CustomStreamMap.__new__(CustomStreamMap)
    names: dict[str, Any] = copy.deepcopy(record)
    names["_"] = record
    names["record"] = record
    names["config"] = CONFIG
    names["__stream_name__"] = "users_alias"
    names["__original_stream_name__"] = "users"
    if property_name in record:
        names["self"] = record[property_name]
    evaluator = simpleeval.EvalWithCompoundTypes(functions=mapper.functions, names=names)
    return evaluator.eval(text)


def ours(text: str, record: dict[str, Any], property_name: str) -> object:
    """Evaluate the rewritten expression in map-conform's scope."""
    names = Names(
        constants={"config": CONFIG, "stream": "users_alias", "source_stream": "users"},
    )
    expression = compile_expr(rewrite_sdk_expression(text), names)
    return expression.evaluate(Row.of(record), record.get(property_name))


def normal(value: object) -> object:
    """Compare a read-only record view and a dict equally."""
    return json.loads(json.dumps(value, default=str)) if not isinstance(value, dt.date) else value


@pytest.mark.parametrize(("text", "record"), CORPUS, ids=[text for text, _ in CORPUS])
def test_sdk_expression_parity(text: str, record: dict[str, Any]) -> None:
    """map-conform gives the SDK's result for every SDK expression in the corpus."""
    expected = sdk_eval(text, record, "email")
    assert normal(ours(text, record, "email")) == normal(expected)


def test_rewrite_keeps_text_that_needs_no_change() -> None:
    """Literals, self and SDK names are left as written."""
    for text in ("'[masked]'", "self.upper()", "__stream_name__", "md5(_['x'])"):
        assert rewrite_sdk_expression(text) == text


def test_rewrite_leaves_comprehension_variables() -> None:
    """Only free names become record reads."""
    assert (
        rewrite_sdk_expression("[x for x in items if x > n]")
        == "[x for x in record['items'] if x > record['n']]"
    )
