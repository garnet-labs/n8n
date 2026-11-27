"""Unit tests for the n8n shadow dependency mirror."""

import base64
import json
import pathlib
import unittest

from mirror import (
    FORK,
    GATE_MARKER,
    HOLD_MARKER,
    SOURCE,
    Mirror,
    finalized_review,
    is_dependency_pr,
    mirror_revision,
    recording_workflow,
    scrub_title,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]


class FakeAPI:
    def __init__(self, responses=None, dry_run=False):
        self.responses = dict(responses or {})
        self.dry_run = dry_run
        self.writes = []
        self.marked_ready = []
        self.counter = 0

    def call(self, repo, path, method="GET", data=None):
        if method != "GET":
            self.writes.append((repo, method, path, data))
            self.counter += 1
            if path == "pulls":
                return {
                    "number": 90 + self.counter,
                    "html_url": f"https://github.com/{FORK}/pull/{90 + self.counter}",
                    "node_id": f"PR_node_{self.counter}",
                    "draft": data.get("draft", False),
                    "state": "open",
                    "head": {"sha": "b" * 40, "ref": data["head"], "repo": {"full_name": FORK}},
                    "base": {"ref": data["base"], "repo": {"full_name": FORK}},
                }
            return {"sha": f"{self.counter:040x}"}
        key = (repo, path)
        if key not in self.responses:
            raise AssertionError(f"Unexpected GET {key}")
        value = self.responses[key]
        if isinstance(value, Exception):
            raise value
        return value

    def pages(self, repo, path):
        value = self.call(repo, path)
        return iter(value)

    def write(self, path, data, method="POST"):
        return self.call(FORK, path, method, data)

    def mark_ready(self, pr, upstream_number):
        self.marked_ready.append((pr["number"], upstream_number))


class ShadowMirrorTests(unittest.TestCase):
    def test_recording_workflow_transforms_repo_file(self):
        raw = (ROOT / ".github/workflows/garnet-record.yml").read_text()
        transformed = recording_workflow(raw)
        self.assertIn("branches: ['master', 'shadow/base/**']", transformed)
        self.assertIn("workflow_dispatch:", transformed)
        self.assertIn("github.event.pull_request.head.sha || github.sha", transformed)
        self.assertIn("persist-credentials: false", transformed)

    def test_bot_filtering_allows_cat_bot_only_with_lockfile(self):
        cat_bot = {"user": {"login": "n8n-cat-bot[bot]", "type": "Bot"}, "changed_files": 2}
        self.assertTrue(
            is_dependency_pr(
                cat_bot,
                [{"filename": "package.json"}, {"filename": "pnpm-lock.yaml"}],
            )
        )
        self.assertFalse(
            is_dependency_pr(
                cat_bot,
                [{"filename": "packages/cli/src/foo.ts"}, {"filename": "package.json"}],
            )
        )

    def test_bot_filtering_rejects_human_prs(self):
        human = {"user": {"login": "alice", "type": "User"}, "changed_files": 2}
        self.assertFalse(
            is_dependency_pr(
                human,
                [{"filename": "package.json"}, {"filename": "pnpm-lock.yaml"}],
            )
        )

    def test_bot_filtering_allows_dependabot(self):
        dep = {"user": {"login": "dependabot[bot]", "type": "Bot"}, "changed_files": 1}
        self.assertTrue(
            is_dependency_pr(dep, [{"filename": "packages/cli/package.json"}])
        )

    def test_scrub_title(self):
        self.assertEqual(
            scrub_title("chore: Bump zod #123 @alice [skip ci] https://example.com"),
            "chore: Bump zod",
        )

    def test_mirror_revision(self):
        pr = {
            "head": {"ref": "shadow/pr/44782-r2", "repo": {"full_name": FORK}},
            "base": {"ref": "shadow/base/44782-r2", "repo": {"full_name": FORK}},
        }
        self.assertEqual(mirror_revision(pr, 44782), 2)

    def test_finalized_review_matches_exact_head_only(self):
        head = "a" * 40
        stale = "b" * 40
        body = (
            "<!-- garnet-runtime-review -->\n"
            "<!-- garnet-control-plane-pr-comment:v1:app.garnet.ai -->\n"
            f"<!-- garnet:commit {head} -->\n"
            f'<!-- garnet:summary {json.dumps({"commit": head, "status": "finalized"})} -->\n'
        )
        comment = {"user": {"login": "garnet-runtime-review[bot]"}, "body": body}
        self.assertTrue(finalized_review(comment, head))
        self.assertFalse(finalized_review(comment, stale))

    def test_ready_if_finalized_marks_draft_ready(self):
        head = "c" * 40
        base = "d" * 40
        existing = {
            "number": 55,
            "state": "open",
            "draft": True,
            "node_id": "PR_55",
            "html_url": f"https://github.com/{FORK}/pull/55",
            "body": f"<!-- garnet-shadow-mirror upstream=44782 upstream_head={head} upstream_base={base} -->",
            "head": {"sha": head, "ref": "shadow/pr/44782", "repo": {"full_name": FORK}},
            "base": {"ref": "shadow/base/44782", "repo": {"full_name": FORK}},
        }
        review_body = (
            "<!-- garnet-runtime-review -->\n"
            "<!-- garnet-control-plane-pr-comment:v1:app.garnet.ai -->\n"
            f"<!-- garnet:commit {head} -->\n"
            f'<!-- garnet:summary {json.dumps({"commit": head, "status": "finalized"})} -->\n'
        )
        api = FakeAPI(
            {
                (FORK, "pulls?state=all"): [existing],
                (FORK, "issues/55/comments"): [
                    {"user": {"login": "garnet-runtime-review[bot]"}, "body": review_body},
                    {"user": {"login": "devin-ai-integration[bot]"}, "body": f"{GATE_MARKER}\nPASS"},
                ],
                (FORK, "pulls/55"): existing,
            }
        )
        mirror = Mirror(api)
        self.assertTrue(mirror.ready_if_finalized(existing, 44782, 1))
        self.assertEqual(api.marked_ready, [(55, 44782)])

    def test_ensure_gate_comment_preserves_existing_verdict(self):
        api = FakeAPI(
            {
                (FORK, "pulls?state=all"): [],
                (FORK, "issues/55/comments"): [
                    {"body": f"{GATE_MARKER}\nPASS"},
                ],
            }
        )
        mirror = Mirror(api)
        mirror.ensure_gate_comment(55)
        self.assertEqual(api.writes, [])

    def test_ensure_gate_comment_posts_hold_when_missing(self):
        api = FakeAPI(
            {
                (FORK, "pulls?state=all"): [],
                (FORK, "issues/55/comments"): [],
            }
        )
        mirror = Mirror(api)
        mirror.ensure_gate_comment(55)
        self.assertEqual(len(api.writes), 1)
        self.assertIn(HOLD_MARKER, api.writes[0][3]["body"])

    def test_tree_copies_reviewer_adapters(self):
        raw_wf = (ROOT / ".github/workflows/garnet-record.yml").read_text()
        encoded = base64.b64encode(raw_wf.encode()).decode()
        api = FakeAPI(
            {
                (FORK, "pulls?state=all"): [],
                (FORK, "contents/.github/workflows/garnet-record.yml?ref=master"): {
                    "content": encoded
                },
                (FORK, "git/trees/master"): {
                    "tree": [
                        {"path": "REVIEW.md", "mode": "100644", "type": "blob", "sha": "1" * 40},
                        {"path": "greptile.json", "mode": "100644", "type": "blob", "sha": "2" * 40},
                        {"path": ".agents", "mode": "040000", "type": "tree", "sha": "3" * 40},
                        {"path": "README.md", "mode": "100644", "type": "blob", "sha": "4" * 40},
                    ]
                },
                (FORK, f"git/commits/{'e' * 40}"): {"tree": {"sha": "f" * 40}},
                (FORK, f"git/trees/{'f' * 40}"): {"tree": []},
            }
        )
        mirror = Mirror(api)
        mirror._load_fork_assets()
        mirror.tree("e" * 40)
        final_tree = api.writes[-1][3]["tree"]
        paths = {item["path"] for item in final_tree}
        self.assertEqual(paths, {".github", "REVIEW.md", "greptile.json", ".agents"})

    def test_dry_run_skips_writes(self):
        base_sha = "1" * 40
        head_sha = "2" * 40
        merge_base = "3" * 40
        pr_obj = {
            "state": "open",
            "changed_files": 2,
            "user": {"login": "n8n-cat-bot[bot]", "type": "Bot"},
            "base": {"sha": base_sha},
            "head": {"sha": head_sha},
            "title": "chore: Bump zod",
        }
        api = FakeAPI(
            {
                (FORK, "pulls?state=all"): [],
                (SOURCE, "pulls/44782"): pr_obj,
                (SOURCE, "pulls/44782/files"): [
                    {"filename": "package.json"},
                    {"filename": "pnpm-lock.yaml"},
                ],
                (SOURCE, f"compare/{base_sha}...{head_sha}"): {
                    "merge_base_commit": {"sha": merge_base}
                },
            },
            dry_run=True,
        )
        mirror = Mirror(api)
        result = mirror.sync(44782)
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["upstream_base"], merge_base)
        self.assertEqual(api.writes, [])


if __name__ == "__main__":
    unittest.main()
