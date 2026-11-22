"""Fake data: the fake step and the fake object, seeded like the SDK (WBS 12.4)."""

from __future__ import annotations

import pytest

from map_conform.errors import ConformError
from map_conform.transforms import fake as fake_module
from tests.plan.test_expressions import STRING, conform, plan_for, problems

# The Singer SDK's own snapshots for these specs (tests/snapshots/mapped_stream/).
SDK_CREDIT_CARDS = ["4201040137208265027", "675987782884", "502011811259"]
SDK_EMAILS = ["zwells@example.org", "josephcunningham@example.com", "lydia62@example.net"]
USERS = [{"email": f"{name}@example.com"} for name in ("alice", "bob", "charlie")]
SEEDED = {"faker": {"seed": 123456, "locale": "en_US"}}


def test_seeded_expression_matches_the_sdk() -> None:
    """fake.credit_card_number() with seed 123456 gives the SDK snapshot's values."""
    out = conform(
        {"cc": {"type": "string", "expr": "fake.credit_card_number()"}},
        {"cc": STRING},
        *([{}] * 3),
        defaults=SEEDED,
    )
    assert [row["cc"] for row in out if row] == SDK_CREDIT_CARDS


def test_seed_instance_idiom_matches_the_sdk() -> None:
    """fake.seed_instance(email) or fake.email(): one fake per real value, as in the SDK."""
    out = conform(
        {"email": {"type": "string", "expr": "fake.seed_instance(value) or fake.email()"}},
        {"email": STRING},
        *USERS,
        defaults={"faker": {"locale": "en_US"}},
    )
    assert [row["email"] for row in out if row] == SDK_EMAILS


def test_fake_step_is_reproducible() -> None:
    """Two runs with the same seed give the same values; the step replaces non-null values."""
    columns = {"name": {"type": "string", "transform": {"fake": "name"}}}
    first = conform(columns, {"name": STRING}, {"name": "a"}, {"name": "b"}, defaults=SEEDED)
    second = conform(columns, {"name": STRING}, {"name": "a"}, {"name": "b"}, defaults=SEEDED)
    assert first == second
    assert first[0] != {"name": "a"}
    assert conform(columns, {"name": STRING}, {"name": None}, defaults=SEEDED) == [{"name": None}]


def test_fake_step_args_and_unique() -> None:
    """Provider arguments are passed; unique never repeats within the run."""
    columns = {
        "n": {"type": "int64", "transform": {"fake": "random_int", "args": [1, 3], "unique": True}}
    }
    out = conform(columns, {"n": STRING}, *([{"n": "x"}] * 3), defaults=SEEDED)
    assert sorted(row["n"] for row in out if row) == [1, 2, 3]
    _, executor = plan_for(columns, {"n": STRING}, defaults=SEEDED)
    for row in range(3):
        executor.run({"n": "x"}, {}, row)
    with pytest.raises(ConformError, match="UniquenessException"):
        executor.run({"n": "x"}, {}, 4)


def test_fake_step_in_an_expression() -> None:
    """The step is also callable as fake(value, provider)."""
    out = conform(
        {"c": {"type": "string", "expr": "fake(value, 'word')"}}, {"c": STRING}, {"c": "x"},
        defaults=SEEDED,
    )  # fmt: skip
    assert out[0] is not None
    assert out[0]["c"].isalpha()


def test_unknown_provider_is_a_compile_error() -> None:
    """The provider is checked when the plan compiles."""
    found = problems({"c": {"type": "string", "transform": {"fake": "nope"}}}, {"c": STRING})
    assert "transform.provider: 'nope' is not a Faker provider" in found[0]


@pytest.mark.parametrize(
    "text", ["fake.seed(1)", "fake.add_provider(str)", "fake.random", "fake.factories"]
)
def test_global_state_is_out_of_reach(text: str) -> None:
    """Global seeding, private state and provider injection are refused."""
    _, executor = plan_for({"c": {"type": "string", "expr": text}}, {"c": STRING})
    with pytest.raises(ConformError, match="not available in expressions"):
        executor.run({"c": "x"}, {}, 1)


def test_missing_extra_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without faker installed, the step and the object say which extra to install."""
    monkeypatch.setattr(fake_module, "available", lambda: False)
    found = problems({"c": {"type": "string", "transform": {"fake": "name"}}}, {"c": STRING})
    assert "fake needs the faker extra" in found[0]
    _, executor = plan_for({"c": {"type": "string", "expr": "fake.name()"}}, {"c": STRING})
    with pytest.raises(ConformError, match="fake needs the faker extra"):
        executor.run({"c": "x"}, {}, 1)
