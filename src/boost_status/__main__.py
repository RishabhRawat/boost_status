import argparse
import subprocess
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

from .github_stats import GithubMetaData, get_git_metadata


def get_repo_url(git_path: str) -> str:
    return subprocess.run(
        ["git", "-C", git_path, "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
    ).stdout.rstrip()


def list_boost_repos(superproject_path: Path) -> Dict[str, Any]:
    return {
        item.name: {
            "url": get_repo_url(str(item)),
            "path": str(item),
        }
        for item in (superproject_path / "libs").iterdir()
        if item.is_dir()
    }


def get_repo_status(repo: Tuple[str, Dict[str, Any]]) -> Dict[str, Any]:
    repo_name, repo_info = repo
    repo_info.update(get_git_metadata(repo_info["path"]))
    del repo_info["path"]
    github_metadata = GithubMetaData(repo_info["url"])
    repo_info["issues"] = github_metadata.get_issue_summary(issue_type="issues")
    repo_info["pull_requests"] = github_metadata.get_issue_summary(
        issue_type="pullRequests"
    )
    return repo_name, repo_info


def get_top_by_statistic(repos, top_count, key):
    return [
        {repo[0]: key(repo[1])}
        for repo in sorted(repos.items(), key=lambda x: key(x[1]), reverse=True)[
            :top_count
        ]
    ]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="path to boost super project git directory")
    parsed_args = parser.parse_args(argv)
    boost_repos = list_boost_repos(Path(parsed_args.path))

    with Pool(2) as p:
        boost_repos = dict(p.map(get_repo_status, boost_repos.items()))

    overall_stats = {
        "Most Open Issues": get_top_by_statistic(
            boost_repos, 5, lambda x: x["issues"]["count"]
        ),
        "Most Open PRs": get_top_by_statistic(
            boost_repos, 5, lambda x: x["pull_requests"]["count"]
        ),
        "Most Open Issues older than 360 days": get_top_by_statistic(
            boost_repos, 5, lambda x: x["issues"]["last_update_360_days"]
        ),
        "Most Open PRs older than 360 days": get_top_by_statistic(
            boost_repos, 5, lambda x: x["pull_requests"]["last_update_360_days"]
        ),
        "Most days since last commit": get_top_by_statistic(
            boost_repos, 5, lambda x: x["days_since_last_commit"]
        ),
    }

    print(yaml.dump({"module stats": boost_repos, "overall stats": overall_stats}))


if __name__ == "__main__":
    main()
