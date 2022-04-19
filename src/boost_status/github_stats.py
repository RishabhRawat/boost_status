import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict

import dateutil.parser
import requests

# Regex created via - https://regex101.com/r/9Fvyvg/1
# Note: does not handle git servers with custom port
GIT_REGEX = re.compile(
    r"(git(@|(://))|(ssh|http(s)?)(://))(([\w\:]+@)?)(?P<hostname>[\w\.]+)([:/])(?P<path>[\w\~\/]+)(\.git)(/)?"
)


def get_git_metadata(git_path: str) -> Dict[str, Any]:
    last_commit_timestamp = int(
        subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=git_path,
            text=True,
            capture_output=True,
        ).stdout
    )
    return {
        "days_since_last_commit": (
            datetime.now() - datetime.fromtimestamp(last_commit_timestamp)
        ).days
    }


@dataclass
class GithubStats:
    count: int = 0
    without_response: int = 0
    without_assignee: int = 0
    pending_response: int = 0
    last_update_30_days: int = 0
    last_update_90_days: int = 0
    last_update_360_days: int = 0

    def __add__(self, other: "GithubStats") -> "GithubStats":
        if isinstance(other, GithubStats):
            return GithubStats(
                count=self.count + other.count,
                without_response=self.without_response + other.without_response,
                without_assignee=self.without_assignee + other.without_assignee,
                pending_response=self.pending_response + other.pending_response,
                last_update_30_days=self.last_update_30_days
                + other.last_update_30_days,
                last_update_90_days=self.last_update_90_days
                + other.last_update_90_days,
                last_update_360_days=self.last_update_360_days
                + other.last_update_360_days,
            )
        else:
            return NotImplementedError()


class GithubMetaData:
    def __init__(self, remote_url) -> None:
        self._requests = requests.Session()
        self._requests.headers.update({"Accept": "application/vnd.github.v3+json"})
        if os.getenv("GITHUB_TOKEN"):
            self._requests.headers.update(
                {"Authorization": f'token {os.getenv("GITHUB_TOKEN")}'}
            )
        self._remote_url = remote_url
        regex_match = GIT_REGEX.match(self._remote_url)
        assert regex_match, f"Invalid remote git url - {remote_url}"
        self._base_url = f"https://api.{regex_match.group('hostname')}/repos/{regex_match.group('path')}"
        self._contributors = self.get_contributors()

    def get_contributors(self):
        response = self._requests.get(f"{self._base_url}/contributors")
        response.raise_for_status()
        return [user["login"] for user in response.json()]

    def get_issue_comment(self, issue_id, comment_number):
        response = self._requests.get(
            f"{self._base_url}/issues/{issue_id}/comments",
            json={"per_page": 1, "page": comment_number},
        )
        response.raise_for_status()
        return response.json()[0]

    def get_issue_summary(self):
        response = self._requests.get(f"{self._base_url}/issues")
        response.raise_for_status()
        response = response.json()

        issue_summary = GithubStats()
        pr_summary = GithubStats()

        for issue in response:
            if issue["state"] == "open":
                days_since_last_update = (
                    datetime.now(timezone.utc)
                    - dateutil.parser.isoparse(issue["updated_at"])
                ).days
                issue_info = GithubStats(
                    count=1,
                    without_response=(1 if issue["comments"] == 0 else 0),
                    without_assignee=(1 if issue["assignee"] is None else 0),
                    last_update_30_days=(1 if days_since_last_update > 30 else 0),
                    last_update_90_days=(1 if days_since_last_update > 90 else 0),
                    last_update_360_days=(1 if days_since_last_update > 360 else 0),
                )
                if issue["comments"] > 0:
                    last_comment = self.get_issue_comment(
                        issue["number"], issue["comments"]
                    )
                    issue_info.pending_response = (
                        1
                        if last_comment["user"]["login"] not in self._contributors
                        else 0
                    )

            if issue.get("pull_request") is None:
                issue_summary += issue_info
            else:
                pr_summary += issue_info

        return asdict(issue_summary), asdict(pr_summary)
