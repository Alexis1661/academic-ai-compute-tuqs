"""
Contract compliance: the running app exposes exactly the operations, status codes and
schemas declared in docs/contracts/openapi.yaml (no hallucinated or missing endpoints).
"""
from pathlib import Path

import pytest
import yaml

from src.main import app

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "openapi.yaml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
CONSTRAINT_KEYS = {"minimum", "maximum", "exclusiveMinimum", "minLength", "maxLength"}


@pytest.fixture(scope="module")
def contract():
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live():
    return app.openapi()


def _operations(spec):
    return {
        (path, method): op
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    }


def _json_ref(container):
    schema = container.get("content", {}).get("application/json", {}).get("schema", {})
    return schema.get("$ref")


def test_openapi_version(contract, live):
    assert contract["openapi"] == live["openapi"] == "3.1.0"


def test_same_operations(contract, live):
    assert set(_operations(contract)) == set(_operations(live))


def test_same_status_codes_and_payload_schemas(contract, live):
    live_ops = _operations(live)
    for key, op in _operations(contract).items():
        live_op = live_ops[key]
        assert set(op["responses"]) == set(live_op["responses"]), key
        for code, response in op["responses"].items():
            assert _json_ref(response) == _json_ref(live_op["responses"][code]), (key, code)
        assert _json_ref(op.get("requestBody", {})) == _json_ref(live_op.get("requestBody", {})), key


def test_component_schemas_match(contract, live):
    live_schemas = live["components"]["schemas"]
    for name, schema in contract["components"]["schemas"].items():
        assert name in live_schemas, name
        live_schema = live_schemas[name]
        assert set(schema["properties"]) == set(live_schema["properties"]), name
        assert set(schema.get("required", [])) == set(live_schema.get("required", [])), name
        for prop, definition in schema["properties"].items():
            declared = {k: v for k, v in definition.items() if k in CONSTRAINT_KEYS}
            actual = {k: v for k, v in live_schema["properties"][prop].items() if k in CONSTRAINT_KEYS}
            assert declared == actual, (name, prop)


def test_no_unplanned_live_schemas(contract, live):
    assert set(live["components"]["schemas"]) <= set(contract["components"]["schemas"])
