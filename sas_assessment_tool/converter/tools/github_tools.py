"""
GitHub REST API v3 interaction tool for the SAS migration pipeline.

Usage:
    python tools/github_tools.py <subcommand> [options]

Required env vars:
    GITHUB_TOKEN        Personal Access Token (scopes: repo, read:org)
    GITHUB_REPO_OWNER   GitHub org or user
    GITHUB_REPO_NAME    Repository name

Subcommands:
    create-pr       Create a pull request
    get-pr          Get PR details and status
    list-prs        List pull requests
    list-comments   List comments on a PR
    add-comment     Add a comment to a PR
    reply-review    Reply to a pull request review comment (thread)
    list-branches   List repository branches
    pipeline-status Get CI check run status for a PR or commit
"""

import argparse
import json
import os
import sys

import requests


def _load_config():
    missing = []
    token = os.environ.get("GITHUB_TOKEN")
    owner = os.environ.get("GITHUB_REPO_OWNER")
    repo = os.environ.get("GITHUB_REPO_NAME")
    if not token:
        missing.append("GITHUB_TOKEN")
    if not owner:
        missing.append("GITHUB_REPO_OWNER")
    if not repo:
        missing.append("GITHUB_REPO_NAME")
    if missing:
        print(
            f"ERROR: Missing required environment variable(s): {', '.join(missing)}\n"
            "Set them before running this tool:\n"
            "  GITHUB_TOKEN        - Personal Access Token (scopes: repo, read:org)\n"
            "  GITHUB_REPO_OWNER   - GitHub org or user (e.g. my-org)\n"
            "  GITHUB_REPO_NAME    - Repository name (e.g. my-repo)",
            file=sys.stderr,
        )
        sys.exit(1)
    return token, owner, repo


class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str, repo: str):
        self.owner = owner
        self.repo = repo
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.BASE}{path}"
        response = self._session.request(method, url, **kwargs)
        if not response.ok:
            print(
                f"ERROR: GitHub API returned {response.status_code} for {method} {url}\n"
                f"{response.text}",
                file=sys.stderr,
            )
            sys.exit(1)
        if response.status_code == 204:
            return {}
        return response.json()

    def _repo(self) -> str:
        return f"/repos/{self.owner}/{self.repo}"

    # --- Pull Requests ---

    def create_pull_request(
        self,
        title: str,
        source: str,
        target: str,
        description: str = "",
        draft: bool = False,
    ) -> dict:
        payload = {
            "title": title,
            "head": source,
            "base": target,
            "body": description,
            "draft": draft,
        }
        data = self._request("POST", f"{self._repo()}/pulls", json=payload)
        return self._normalize_pr(data)

    def get_pull_request(self, pr_id: int) -> dict:
        data = self._request("GET", f"{self._repo()}/pulls/{pr_id}")
        return self._normalize_pr(data)

    def list_pull_requests(self, state: str = "open") -> list:
        params = {"state": state, "per_page": 100}
        data = self._request("GET", f"{self._repo()}/pulls", params=params)
        return [self._normalize_pr(pr) for pr in data]

    def _normalize_pr(self, pr: dict) -> dict:
        if pr.get("draft"):
            status = "draft"
        elif pr.get("merged_at"):
            status = "merged"
        else:
            status = pr.get("state", "open")  # open or closed
        return {
            "id": pr["number"],
            "title": pr["title"],
            "status": status,
            "url": pr["html_url"],
            "source_branch": pr["head"]["ref"],
            "target_branch": pr["base"]["ref"],
        }

    # --- Comments ---

    def list_pr_comments(self, pr_id: int) -> list:
        params = {"per_page": 100}
        data = self._request(
            "GET", f"{self._repo()}/issues/{pr_id}/comments", params=params
        )
        return [
            {
                "id": c["id"],
                "author": c["user"]["login"],
                "body": c["body"],
                "created_at": c["created_at"],
                "url": c["html_url"],
            }
            for c in data
        ]

    def add_pr_comment(self, pr_id: int, body: str) -> dict:
        payload = {"body": body}
        data = self._request(
            "POST", f"{self._repo()}/issues/{pr_id}/comments", json=payload
        )
        return {
            "id": data["id"],
            "author": data["user"]["login"],
            "body": data["body"],
            "url": data["html_url"],
        }

    def add_pull_request_review_reply(
        self, pr_id: int, in_reply_to: int, body: str
    ) -> dict:
        """Reply to an existing review comment (REST: in_reply_to)."""
        payload = {"body": body, "in_reply_to": in_reply_to}
        data = self._request(
            "POST", f"{self._repo()}/pulls/{pr_id}/comments", json=payload
        )
        return {
            "id": data["id"],
            "author": data["user"]["login"],
            "body": data["body"],
            "url": data["html_url"],
            "in_reply_to": data.get("in_reply_to"),
        }

    # --- Branches ---

    def list_branches(self) -> list:
        params = {"per_page": 100}
        data = self._request("GET", f"{self._repo()}/branches", params=params)
        return [b["name"] for b in data]

    # --- CI / Pipeline ---

    def get_pipeline_status(self, pr_id: int = None, commit_sha: str = None) -> list:
        if pr_id is not None:
            pr = self._request("GET", f"{self._repo()}/pulls/{pr_id}")
            commit_sha = pr["head"]["sha"]
        if not commit_sha:
            print("ERROR: Provide --pr-id or --commit", file=sys.stderr)
            sys.exit(1)
        data = self._request(
            "GET", f"{self._repo()}/commits/{commit_sha}/check-runs"
        )
        runs = data.get("check_runs", [])
        return [
            {
                "name": r["name"],
                "state": self._normalize_check_state(r["status"], r["conclusion"]),
                "url": r["html_url"],
            }
            for r in runs
        ]

    def _normalize_check_state(self, status: str, conclusion) -> str:
        if status == "in_progress":
            return "running"
        if status == "queued":
            return "pending"
        # status == "completed"
        if conclusion == "success":
            return "success"
        if conclusion in ("failure", "timed_out", "action_required"):
            return "failed"
        return conclusion or status


# --- CLI ---

def _print(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        prog="github_tools",
        description="GitHub REST API v3 tool for the SAS migration pipeline.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # create-pr
    p_create = sub.add_parser("create-pr", help="Create a pull request")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--source", required=True, help="Source branch")
    p_create.add_argument("--target", required=True, help="Target branch")
    p_create.add_argument("--description", default="")
    p_create.add_argument("--draft", action="store_true")

    # get-pr
    p_get = sub.add_parser("get-pr", help="Get PR details and status")
    p_get.add_argument("--id", type=int, required=True, dest="pr_id")

    # list-prs
    p_list = sub.add_parser("list-prs", help="List pull requests")
    p_list.add_argument("--state", default="open", choices=["open", "closed", "all"])

    # list-comments
    p_comments = sub.add_parser("list-comments", help="List comments on a PR")
    p_comments.add_argument("--pr-id", type=int, required=True)

    # add-comment
    p_add = sub.add_parser("add-comment", help="Add a comment to a PR")
    p_add.add_argument("--pr-id", type=int, required=True)
    p_add.add_argument("--body", required=True)

    # reply-review (thread on a line/file review, not issue comment)
    p_reply = sub.add_parser(
        "reply-review", help="Reply to a pull request review comment"
    )
    p_reply.add_argument("--pr-id", type=int, required=True)
    p_reply.add_argument(
        "--in-reply-to",
        type=int,
        required=True,
        dest="in_reply_to",
        help="Review comment id (from API /pulls/comments)",
    )
    grp = p_reply.add_mutually_exclusive_group(required=True)
    grp.add_argument("--body", help="Reply body (plain text / markdown)")
    grp.add_argument(
        "--body-file",
        dest="body_file",
        metavar="PATH",
        help="Read reply body from UTF-8 file",
    )

    # list-branches
    sub.add_parser("list-branches", help="List repository branches")

    # pipeline-status
    p_pipe = sub.add_parser("pipeline-status", help="Get CI check run status")
    group = p_pipe.add_mutually_exclusive_group(required=True)
    group.add_argument("--pr-id", type=int)
    group.add_argument("--commit", dest="commit_sha")

    args = parser.parse_args()
    token, owner, repo = _load_config()
    client = GitHubClient(token, owner, repo)

    if args.cmd == "create-pr":
        _print(client.create_pull_request(
            args.title, args.source, args.target, args.description, args.draft
        ))
    elif args.cmd == "get-pr":
        _print(client.get_pull_request(args.pr_id))
    elif args.cmd == "list-prs":
        _print(client.list_pull_requests(args.state))
    elif args.cmd == "list-comments":
        _print(client.list_pr_comments(args.pr_id))
    elif args.cmd == "add-comment":
        _print(client.add_pr_comment(args.pr_id, args.body))
    elif args.cmd == "reply-review":
        if getattr(args, "body_file", None):
            with open(args.body_file, encoding="utf-8") as f:
                reply_body = f.read()
        else:
            reply_body = args.body
        _print(
            client.add_pull_request_review_reply(
                args.pr_id, args.in_reply_to, reply_body
            )
        )
    elif args.cmd == "list-branches":
        _print(client.list_branches())
    elif args.cmd == "pipeline-status":
        _print(client.get_pipeline_status(pr_id=args.pr_id, commit_sha=args.commit_sha))


if __name__ == "__main__":
    main()
