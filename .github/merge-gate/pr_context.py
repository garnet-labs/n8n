"""Resolve recorder events and publish only a current-head verdict using API data."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from gate import BOT, parse_summary

MARKER = "<!-- stamphog-sticky-review -->"
SHA = re.compile(r"[0-9a-f]{40}")


def api(repo, path, method="GET", data=None):
    args = ["gh", "api", "-X", method, f"repos/{repo}/{path}"]
    if method == "GET":
        args += ["--paginate", "--slurp"]
    else:
        args += ["--input", "-"]
    result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                            check=True, capture_output=True, text=True, timeout=60)
    value = json.loads(result.stdout)
    if method != "GET":
        return value
    return [item for page in value for item in page] if value and isinstance(value[0], list) else value[0]


def current_pr(repo, number):
    pr = api(repo, f"pulls/{number}")
    if (pr["state"] != "open" or
            (pr["head"].get("repo") or {}).get("full_name") != repo or not SHA.fullmatch(pr["head"]["sha"])):
        return None
    return pr


def resolve(repo, event_name, event):
    expected = None
    if event_name == "workflow_dispatch":
        number = str(event.get("inputs", {}).get("pr_number", ""))
        if not number.isdecimal() or int(number) < 1:
            raise ValueError("pr_number must be a positive integer")
    elif event_name == "issue_comment":
        if event.get("comment", {}).get("user", {}).get("login") != BOT:
            return None
        summary = parse_summary(event["comment"]["body"])
        if not event.get("issue", {}).get("pull_request") or summary is None:
            return None
        expected = summary.get("commit")
        if summary.get("status") != "finalized" or not isinstance(expected, str) or not SHA.fullmatch(expected):
            return None
        number = str(event["issue"]["number"])
    elif event_name == "workflow_run":
        run = event["workflow_run"]
        if (run.get("name") != "Garnet Runtime Visibility" or run.get("status") != "completed" or
                run.get("path") != ".github/workflows/garnet-record.yml" or
                run.get("repository", {}).get("full_name") != repo):
            return None
        expected = run["head_sha"]
        if not SHA.fullmatch(expected):
            return None
        candidates = api(repo, f"commits/{expected}/pulls")
        candidates = [p for p in candidates if p["state"] == "open" and p["head"]["sha"] == expected
                      and p["head"].get("repo", {}).get("full_name") == repo]
        if len(candidates) != 1:
            return None
        number = str(candidates[0]["number"])
    else:
        raise ValueError("unsupported event")
    pr = current_pr(repo, number)
    if pr is None or (expected is not None and pr["head"]["sha"] != expected):
        return None
    return number, pr["head"]["sha"]


def wait_record(repo, number, head, timeout=900):
    deadline = time.monotonic() + timeout
    while True:
        pr = current_pr(repo, number)
        if pr is None or pr["head"]["sha"] != head:
            return False
        comments = api(repo, f"issues/{number}/comments")
        for comment in reversed(comments):
            if comment["user"]["login"] != BOT:
                continue
            summary = parse_summary(comment.get("body", ""))
            if summary and summary.get("commit") == head and summary.get("status") == "finalized":
                return True
        if time.monotonic() >= deadline:
            raise RuntimeError("No finalized head-bound Garnet record; no verdict published")
        time.sleep(30)


def publish(repo, number, head, verdict):
    if not number.isdecimal() or not SHA.fullmatch(head):
        raise ValueError("invalid PR identity")
    if verdict.get("head_sha") != head:
        raise ValueError("verdict does not match resolved head")
    outcome = verdict.get("final_verdict", "")
    if not re.fullmatch(r"[A-Z_]+", outcome):
        raise ValueError("missing or unsupported verdict")
    pr = current_pr(repo, number)
    if pr is None or pr["head"]["sha"] != head:
        print("head moved; verdict not published")
        return
    comments = api(repo, f"issues/{number}/comments")
    mine = [c for c in comments if c["user"]["login"] == "github-actions[bot]" and c.get("body", "").startswith(MARKER)]
    count = re.search(r"stamphog-review-count:(\d+)", mine[-1]["body"]) if mine else None
    body = (f"{MARKER}\n<!-- stamphog-review-count:{int(count[1]) + 1 if count else 1} -->\n"
            f"> [!NOTE]\n> 🤖 stamphog reviewed `{head}` — verdict: **{outcome}**\n\n"
            + (verdict.get("review_body") or "No review prose; see the verdict artifact."))
    pr = current_pr(repo, number)
    if pr is None or pr["head"]["sha"] != head:
        print("head moved; verdict not published")
        return
    if mine:
        api(repo, f"issues/comments/{mine[-1]['id']}", "PATCH", {"body": body})
    else:
        api(repo, f"issues/{number}/comments", "POST", {"body": body})


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    if repo != "garnet-labs/n8n":
        raise ValueError("unexpected repository")
    if sys.argv[1] == "resolve":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        target = resolve(repo, os.environ["GITHUB_EVENT_NAME"], event)
        ready = target is not None and wait_record(repo, *target)
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"ready={str(ready).lower()}\n")
            if ready:
                output.write(f"number={target[0]}\nhead={target[1]}\n")
    elif sys.argv[1] == "publish":
        publish(repo, sys.argv[2], sys.argv[3], json.loads(Path(sys.argv[4]).read_text()))
    else:
        raise ValueError("unsupported command")


if __name__ == "__main__":
    main()
