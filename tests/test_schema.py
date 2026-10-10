import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from crawler.cli import load_schema

FIXTURE = Path(__file__).parent / "fixtures" / "incident_valid.json"


@pytest.fixture(scope="module")
def validator():
    return Draft202012Validator(load_schema(), format_checker=FormatChecker())


@pytest.fixture
def record():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_valid_record_passes(validator, record):
    validator.validate(record)


def test_unknown_field_is_rejected(validator, record):
    # additionalProperties=false is what keeps a stray "victim_name" field out.
    record["victim_name"] = "x"
    assert not validator.is_valid(record)


@pytest.mark.parametrize("field,value", [
    ("origin", "war"),
    ("nfirs_type", 999),
    ("severity", 5),
    ("deaths", -1),
    ("id", "LB-2026-1"),
])
def test_out_of_vocabulary_values_are_rejected(validator, record, field, value):
    bad = copy.deepcopy(record)
    bad[field] = value
    assert not validator.is_valid(bad)


def test_a_record_needs_at_least_one_source(validator, record):
    record["sources"] = []
    assert not validator.is_valid(record)
