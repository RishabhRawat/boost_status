import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict

import dateutil.parser
import requests

GIT_REGEX = re.compile(
    r"((https://github\.com/)|(git@github\.com:))(?P<org>[\w]+)/(?P<name>[\w]+).git"
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
    pending_response: int = 0
    last_update_30_days: int = 0
    last_update_90_days: int = 0
    last_update_360_days: int = 0

    def __add__(self, other: "GithubStats") -> "GithubStats":
        if isinstance(other, GithubStats):
            return GithubStats(
                count=self.count + other.count,
                without_response=self.without_response + other.without_response,
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
        self._requests.headers.update(
            {"Accept": "application/vnd.github.v3+json", "User-Agent": "requests"}
        )
        if os.getenv("GITHUB_TOKEN"):
            self._requests.headers.update(
                {"Authorization": f'token {os.getenv("GITHUB_TOKEN")}'}
            )
        self._remote_url = remote_url
        regex_match = GIT_REGEX.match(self._remote_url)
        assert regex_match, f"Invalid remote git url - {remote_url}"
        self._base_url = f"https://api.github.com"
        self._org = regex_match.group("org")
        self._name = regex_match.group("name")
        self._contributors = self.get_contributors()

    def get_contributors(self):
        response = self._requests.get(
            f"{self._base_url}/repos/{self._org}/{self._name}/contributors"
        )
        response.raise_for_status()
        return [user["login"] for user in response.json()]

    def get_issue_summary(self, issue_type="issue"):
        page_size = 100
        graphql_query = """{{
            repository(owner: "{org_name}", name: "{repo_name}") {{
                {issue_type}(states: [OPEN], first: {page_size}{cursor_string}) {{
                nodes {{
                    id
                    author{{login}}
                    updatedAt
                    comments(last:1) {{
                        totalCount
                        nodes {{
                            author{{login}}
                        }}
                    }}
                }}
                pageInfo {{
                    endCursor
                    startCursor
                }}
                totalCount
                }}
            }}
        }}"""

        issue_list = []
        while True:
            cursor = None
            response = self._requests.post(
                f"{self._base_url}/graphql",
                json={
                    "query": graphql_query.format(
                        org_name=self._org,
                        repo_name=self._name,
                        issue_type=issue_type,
                        page_size=page_size,
                        cursor_string=f', after: "{cursor}"' if cursor else "",
                    )
                },
            )
            if response.status_code > 400:
                print(response.text, flush=True)
            try:
                response.raise_for_status()
            except:
                print("ERROR: ", response.status_code, response.content, response.text, flush=True)
                raise
            response = response.json()["data"]["repository"][issue_type]
            cursor = response["pageInfo"]["endCursor"]
            issue_list.extend(response["nodes"])
            if len(issue_list) >= response["totalCount"]:
                break

        issue_summary = GithubStats()

        for issue in issue_list:
            days_since_last_update = (
                datetime.now(timezone.utc)
                - dateutil.parser.isoparse(issue["updatedAt"])
            ).days
            issue_info = GithubStats(
                count=1,
                without_response=(1 if issue["comments"]["totalCount"] == 0 else 0),
                last_update_30_days=(1 if days_since_last_update > 30 else 0),
                last_update_90_days=(1 if days_since_last_update > 90 else 0),
                last_update_360_days=(1 if days_since_last_update > 360 else 0),
            )
            if issue["comments"]["totalCount"] > 0:
                last_comment_author = issue["comments"]["nodes"][0]["author"]
                last_comment_author = (
                    last_comment_author["login"] if last_comment_author else "ghost"
                )
                issue_info.pending_response = (
                    1 if last_comment_author in self._contributors else 0
                )
            issue_summary += issue_info

        return asdict(issue_summary)
