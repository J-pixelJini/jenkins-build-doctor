"""
Thin wrapper around the Jenkins REST API.

Only three operations are needed for this tool:
  1. Find the build number to inspect (defaults to the last failed build).
  2. Fetch that build's plain-text console log.
  3. Re-trigger the job.

Auth is done with a Jenkins API token (never a raw password), read from
environment variables so nothing sensitive ever lands in code or logs.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests


class JenkinsClientError(RuntimeError):
    pass


@dataclass
class JenkinsConfig:
    base_url: str
    user: str
    api_token: str

    @classmethod
    def from_env(cls) -> "JenkinsConfig":
        base_url = os.environ.get("JENKINS_URL", "").rstrip("/")
        user = os.environ.get("JENKINS_USER", "")
        api_token = os.environ.get("JENKINS_API_TOKEN", "")
        if not base_url or not user or not api_token:
            raise JenkinsClientError(
                "Missing Jenkins config. Set JENKINS_URL, JENKINS_USER, "
                "JENKINS_API_TOKEN as environment variables (an API token, "
                "not your account password — generate one under "
                "Jenkins > your user > Configure > API Token)."
            )
        return cls(base_url=base_url, user=user, api_token=api_token)


class JenkinsClient:
    def __init__(self, config: JenkinsConfig, timeout: int = 15):
        self.config = config
        self.timeout = timeout
        self._auth = (config.user, config.api_token)

    def _get(self, path: str, **kwargs):
        url = f"{self.config.base_url}{path}"
        resp = requests.get(url, auth=self._auth, timeout=self.timeout, **kwargs)
        if resp.status_code == 404:
            raise JenkinsClientError(f"Not found: {url}")
        resp.raise_for_status()
        return resp

    def _post(self, path: str, **kwargs):
        url = f"{self.config.base_url}{path}"
        resp = requests.post(url, auth=self._auth, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp

    def last_failed_build_number(self, job_name: str) -> int:
        resp = self._get(f"/job/{job_name}/lastFailedBuild/api/json")
        data = resp.json()
        return data["number"]

    def console_log(self, job_name: str, build_number: int | str) -> str:
        resp = self._get(f"/job/{job_name}/{build_number}/consoleText")
        return resp.text

    def trigger_build(self, job_name: str) -> str:
        """Re-triggers the job. Returns the queue item URL Jenkins hands back,
        which is how you find the new build number once it starts running."""
        resp = self._post(f"/job/{job_name}/build")
        queue_url = resp.headers.get("Location", "")
        return queue_url

    def wait_for_queued_build_number(
        self, queue_url: str, poll_seconds: float = 2.0, max_wait_seconds: float = 60.0
    ) -> int | None:
        """Polls a Jenkins queue item until it's assigned a real build number,
        or gives up after max_wait_seconds (job may just be queued behind others)."""
        if not queue_url:
            return None
        elapsed = 0.0
        while elapsed < max_wait_seconds:
            r = requests.get(
                f"{queue_url.rstrip('/')}/api/json", auth=self._auth, timeout=self.timeout
            )
            if r.status_code == 200:
                data = r.json()
                executable = data.get("executable")
                if executable and "number" in executable:
                    return executable["number"]
            time.sleep(poll_seconds)
            elapsed += poll_seconds
        return None
