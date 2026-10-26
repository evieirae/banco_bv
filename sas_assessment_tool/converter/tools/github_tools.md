
# Github Tools — Build Record

## Original Request

```prompt
I need to create tools for this project so it can interact with github. it should be able to create pull requests, read and write comments on pull requests, see the status of a pull request (e.g. draft, open, merged), list all branches in the repository and see the resulting status of the CI pipeline triggered by the PR or branch event.
```

---

Here is a draft plan to refine:

# Plan: GitHub Interaction Tools

## Context
The SAS migration tool needs the ability for AI agents (and developers) to interact with GitHub programmatically: creating pull requests after conversions, commenting audit results on PRs, checking PR status, listing branches, and monitoring CI pipelines. The repo remote is currently Bitbucket but these tools target GitHub specifically (the user will provide a PAT for testing). Implementation will be a standalone Python module (`tools/github_tools.py`) that the agent calls via Bash, with no Node.js/MCP dependency.

---

## Files to Create or Modify

| Action | Path |
|--------|------|
| **Create** | `tools/github_tools.py` |
| **Create** | `.cursor/skills/github/SKILL.md` |
| **Modify** | `requirements.txt` |
| **Modify** | `.claude/settings.json` |
| **Modify** | `CLAUDE.md` |

---

## 1. `tools/github_tools.py` — Core Module

### Authentication & Configuration (env vars)
```
GITHUB_TOKEN        Personal Access Token (scopes: repo, read:org)
GITHUB_REPO_OWNER   GitHub org or user (e.g. indiciumtech)
GITHUB_REPO_NAME    Repository name (e.g. sas_assessment_tool)
```
The module reads these at startup via `os.environ`, prints a clear diagnostic and exits non-zero if any are missing.

### GitHub REST API v3 Endpoints Used
| Operation | Method | Endpoint |
|-----------|--------|----------|
| Create PR | POST | `/repos/{owner}/{repo}/pulls` |
| Get PR (status) | GET | `/repos/{owner}/{repo}/pulls/{pr_id}` |
| List PRs | GET | `/repos/{owner}/{repo}/pulls?state={state}` |
| List PR comments | GET | `/repos/{owner}/{repo}/issues/{pr_id}/comments` |
| Add PR comment | POST | `/repos/{owner}/{repo}/issues/{pr_id}/comments` |
| List branches | GET | `/repos/{owner}/{repo}/branches` |
| CI check runs | GET | `/repos/{owner}/{repo}/commits/{sha}/check-runs` |

### Internal Class
```python
class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token, owner, repo): ...
    def _request(self, method, path, **kwargs) -> dict | list: ...  # raises on 4xx/5xx

    def create_pull_request(self, title, source, target, description="", draft=False) -> dict
    def get_pull_request(self, pr_id) -> dict          # normalized: id, title, status, url, source_branch, target_branch
    def list_pull_requests(self, state="open") -> list
    def list_pr_comments(self, pr_id) -> list
    def add_pr_comment(self, pr_id, body) -> dict
    def list_branches(self) -> list[str]
    def get_pipeline_status(self, pr_id=None, commit_sha=None) -> list  # resolves PR→head SHA if pr_id given
```

PR status normalized from GitHub's `state` + `draft` fields → `"draft" | "open" | "merged" | "closed"`.

### CLI Interface (argparse subcommands)
```
python tools/github_tools.py create-pr
    --title "feat: ..."  --source <branch>  --target main
    [--description "..."]  [--draft]

python tools/github_tools.py get-pr       --id <number>
python tools/github_tools.py list-prs     [--state open|closed|all]
python tools/github_tools.py list-comments --pr-id <number>
python tools/github_tools.py add-comment   --pr-id <number> --body "..."
python tools/github_tools.py list-branches
python tools/github_tools.py pipeline-status --pr-id <number>
python tools/github_tools.py pipeline-status --commit <sha>
```
All commands print **JSON to stdout**. Exit 0 on success, non-zero on HTTP errors. Empty lists (`[]`) are valid successes.

---

## 2. `requirements.txt`
Add one line:
```
requests>=2.32.0
```

---

## 3. `.cursor/skills/github/SKILL.md`
New skill file invoked with `/github`. Follows the structure of existing skills (`auditor`, `tradutor`, etc.).

Content covers:
- Required env vars and how to set them
- All 7 CLI operations with examples
- Integration hook: after `/orchestrator` completes, optionally run `/github` to open a PR with the audit report as the PR description body

---

## 4. `.claude/settings.json`
Add one permission to the `allow` array:
```json
"Bash(python tools/github_tools.py *)"
```
(The existing `Bash(python *)` already grants this; adding the explicit entry documents intent and survives future wildcard tightening.)

---

## 5. `CLAUDE.md`
Add a short entry under the **Commands** section:
```markdown
### Interact with GitHub (PR, comments, branches, CI)
```bash
python tools/github_tools.py <subcommand> [options]
# Subcommands: create-pr, get-pr, list-prs, list-comments, add-comment, list-branches, pipeline-status
# Requires env vars: GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME
```
```

---

## Implementation Order
1. Create `tools/github_tools.py`
2. Add `requests>=2.32.0` to `requirements.txt`
3. Create `.cursor/skills/github/SKILL.md`
4. Update `.claude/settings.json`
5. Update `CLAUDE.md`

Steps 1–5 are independent and can be done in parallel.

---

## Verification
1. **Missing env vars** — run without env vars set → should print diagnostic and exit non-zero.
2. **List branches** — `python tools/github_tools.py list-branches` → JSON array of branch names.
3. **List PRs** — `python tools/github_tools.py list-prs` → JSON array (possibly `[]`).
4. **Create PR** — create a test branch, push it, run `create-pr --draft` → verify PR appears in GitHub UI.
5. **Add + read comment** — `add-comment` then `list-comments` → verify round-trip.
6. **Pipeline status** — `pipeline-status --pr-id <id>` → JSON array of check run results.
7. **pip install** — `pip install -r requirements.txt` must succeed cleanly.