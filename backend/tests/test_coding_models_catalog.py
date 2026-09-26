import asyncio

import coding
import pytest


def _models_response():
    router = coding.build_coding_router(None)
    route = next(route for route in router.routes if route.path == "/api/code/models")
    return asyncio.run(route.endpoint())


def test_bedrock_coding_models_are_available_when_configured(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-token")
    monkeypatch.setattr(coding, "has_python_package", lambda name: name == "boto3")

    catalog = _models_response()
    bedrock_models = [model for model in catalog["models"] if model["provider"] == "bedrock"]

    assert {model["id"] for model in bedrock_models} == {"bedrock-claude-sonnet", "bedrock-vision"}
    assert all(model["configured"] for model in bedrock_models)
    assert catalog["providers"]["bedrock"]["configured"]


def test_bedrock_coding_models_explain_missing_setup(monkeypatch):
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.setattr(coding, "has_python_package", lambda name: name == "boto3")

    catalog = _models_response()
    bedrock_models = [model for model in catalog["models"] if model["provider"] == "bedrock"]

    assert len(bedrock_models) == 2
    assert all(not model["configured"] for model in bedrock_models)
    assert all("AWS_BEARER_TOKEN_BEDROCK" in model["reason"] for model in bedrock_models)


@pytest.mark.parametrize("given", [
    "github.com/Areveitech/AreveiTechFrontend.",
    "www.github.com/Areveitech/AreveiTechFrontend",
    "https://github.com/Areveitech/AreveiTechFrontend",
])
def test_github_repo_url_accepts_common_forms(given):
    assert coding.normalize_github_repo_url(given) == "https://github.com/Areveitech/AreveiTechFrontend"


def test_github_repo_url_rejects_other_hosts():
    with pytest.raises(ValueError):
        coding.normalize_github_repo_url("https://github.com.evil.test/owner/repo")
