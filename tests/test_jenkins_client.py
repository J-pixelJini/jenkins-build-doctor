"""
Unit tests for jenkins_client.py, using mocked HTTP responses rather than a
live Jenkins server (none is available in this environment). This verifies
the request/response handling logic — URL construction, auth, the CSRF
crumb flow, JSON parsing, error handling — independent of a real server.
It does not prove a real Jenkins instance behaves exactly like these mocks;
that's the one part of this repo that has only been verified this way,
not against a live server.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from build_agent.jenkins_client import JenkinsClient, JenkinsClientError, JenkinsConfig


@pytest.fixture
def config():
    return JenkinsConfig(base_url="https://jenkins.example.com", user="alice", api_token="tok123")


@pytest.fixture
def client(config):
    return JenkinsClient(config)


def _mock_response(status_code=200, json_data=None, text="", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.headers = headers or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_config_from_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("JENKINS_URL", raising=False)
    monkeypatch.delenv("JENKINS_USER", raising=False)
    monkeypatch.delenv("JENKINS_API_TOKEN", raising=False)
    with pytest.raises(JenkinsClientError):
        JenkinsConfig.from_env()


def test_config_from_env_succeeds_when_set(monkeypatch):
    monkeypatch.setenv("JENKINS_URL", "https://jenkins.example.com/")
    monkeypatch.setenv("JENKINS_USER", "alice")
    monkeypatch.setenv("JENKINS_API_TOKEN", "tok123")
    config = JenkinsConfig.from_env()
    assert config.base_url == "https://jenkins.example.com"  # trailing slash stripped
    assert config.user == "alice"


def test_last_failed_build_number(client):
    with patch("build_agent.jenkins_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response(json_data={"number": 42})
        result = client.last_failed_build_number("my-service")
        assert result == 42
        called_url = mock_get.call_args[0][0]
        assert called_url == "https://jenkins.example.com/job/my-service/lastFailedBuild/api/json"


def test_console_log_returns_text(client):
    with patch("build_agent.jenkins_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response(text="BUILD FAILURE\n...")
        result = client.console_log("my-service", 42)
        assert result == "BUILD FAILURE\n..."


def test_get_raises_on_404(client):
    with patch("build_agent.jenkins_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response(status_code=404)
        with pytest.raises(JenkinsClientError):
            client.last_failed_build_number("no-such-job")


def test_trigger_build_fetches_and_sends_crumb(client):
    """The important regression test: trigger_build must fetch a CSRF crumb
    first and attach it to the POST, since Jenkins rejects POSTs without one
    when CSRF protection is enabled (the default in modern Jenkins)."""
    crumb_resp = _mock_response(
        json_data={"crumbRequestField": "Jenkins-Crumb", "crumb": "abc123"}
    )
    build_resp = _mock_response(headers={"Location": "https://jenkins.example.com/queue/item/99/"})

    with patch("build_agent.jenkins_client.requests.get", return_value=crumb_resp) as mock_get, \
         patch("build_agent.jenkins_client.requests.post", return_value=build_resp) as mock_post:
        queue_url = client.trigger_build("my-service")

    assert queue_url == "https://jenkins.example.com/queue/item/99/"
    mock_get.assert_called_once_with(
        "https://jenkins.example.com/crumbIssuer/api/json", auth=client._auth, timeout=client.timeout
    )
    _, post_kwargs = mock_post.call_args
    assert post_kwargs["headers"] == {"Jenkins-Crumb": "abc123"}


def test_trigger_build_without_csrf_protection(client):
    """When an instance has CSRF protection disabled, /crumbIssuer 404s and
    the client should just proceed without a crumb header rather than fail."""
    no_crumb_resp = _mock_response(status_code=404)
    build_resp = _mock_response(headers={"Location": "https://jenkins.example.com/queue/item/5/"})

    with patch("build_agent.jenkins_client.requests.get", return_value=no_crumb_resp), \
         patch("build_agent.jenkins_client.requests.post", return_value=build_resp) as mock_post:
        queue_url = client.trigger_build("my-service")

    assert queue_url == "https://jenkins.example.com/queue/item/5/"
    _, post_kwargs = mock_post.call_args
    assert post_kwargs["headers"] == {}


def test_crumb_is_cached_across_calls(client):
    """The crumb should only be fetched once per client, not once per POST."""
    crumb_resp = _mock_response(json_data={"crumbRequestField": "Jenkins-Crumb", "crumb": "abc123"})
    build_resp = _mock_response(headers={"Location": "https://jenkins.example.com/queue/item/1/"})

    with patch("build_agent.jenkins_client.requests.get", return_value=crumb_resp) as mock_get, \
         patch("build_agent.jenkins_client.requests.post", return_value=build_resp):
        client.trigger_build("service-a")
        client.trigger_build("service-b")

    assert mock_get.call_count == 1


def test_wait_for_queued_build_number_returns_number_once_assigned(client):
    pending = _mock_response(json_data={})
    ready = _mock_response(json_data={"executable": {"number": 7}})

    with patch("build_agent.jenkins_client.requests.get", side_effect=[pending, ready]), \
         patch("build_agent.jenkins_client.time.sleep"):
        result = client.wait_for_queued_build_number(
            "https://jenkins.example.com/queue/item/1/", poll_seconds=0.01, max_wait_seconds=1
        )
    assert result == 7


def test_wait_for_queued_build_number_gives_up_after_timeout(client):
    pending = _mock_response(json_data={})

    with patch("build_agent.jenkins_client.requests.get", return_value=pending), \
         patch("build_agent.jenkins_client.time.sleep"):
        result = client.wait_for_queued_build_number(
            "https://jenkins.example.com/queue/item/1/", poll_seconds=0.01, max_wait_seconds=0.03
        )
    assert result is None


def test_wait_for_queued_build_number_returns_none_for_empty_queue_url(client):
    assert client.wait_for_queued_build_number("") is None
