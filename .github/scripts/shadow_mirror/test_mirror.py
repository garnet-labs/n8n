"""Unit tests for the n8n shadow dependency mirror."""

import base64
import datetime
import pathlib
import unittest

from mirror import (
    API,
    FORK,
    SOURCE,
    Mirror,
    is_dependency_pr,
    mirror_revision,
    recently_merged,
    recording_workflow,
    scrub_title,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]


class FakeAPI:
    def __init__(self, responses=None, dry_run=False):
        self.responses = dict(responses or {})
        self.dry_run = dry_run
        self.writes = []
        self.counter = 0

    def call(self, repo, path, method="GET", data=None):
        if method != "GET":
            self.writes.append((repo, method, path, data))
            self.counter += 1
            if path == "pulls":
                return {
                    "number": 90 + self.counter,
                    "html_url": f"https://github.com/{FORK}/pull/{90 + self.counter}",
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

    def test_tree_retains_only_garnet_recorder_workflow(self):
        raw_wf = (ROOT / ".github/workflows/garnet-record.yml").read_text()
        encoded = base64.b64encode(raw_wf.encode()).decode()
        api = FakeAPI(
            {
                (FORK, "pulls?state=all"): [],
                (FORK, "contents/.github/workflows/garnet-record.yml?ref=master"): {
                    "content": encoded
                },
                (FORK, f"git/commits/{'e' * 40}"): {"tree": {"sha": "f" * 40}},
                (FORK, f"git/trees/{'f' * 40}"): {"tree": []},
            }
        )
        mirror = Mirror(api)
        mirror.workflow = recording_workflow(raw_wf)
        mirror.tree("e" * 40)
        final_tree = api.writes[-1][3]["tree"]
        self.assertEqual([item["path"] for item in final_tree], [".github"])

    def test_recently_merged_uses_lookback(self):
        now = datetime.datetime(2026, 11, 27, tzinfo=datetime.timezone.utc)
        self.assertTrue(recently_merged({"merged_at": "2026-11-20T00:00:00Z"}, now))
        self.assertFalse(recently_merged({"merged_at": "2026-11-16T00:00:00Z"}, now))
        self.assertFalse(recently_merged({"merged_at": None}, now))

    def test_open_backfilled_mirror_stays_in_window(self):
        now = datetime.datetime(2026, 11, 27, tzinfo=datetime.timezone.utc)
        pr = {"merged_at": "2026-10-16T00:00:00Z"}
        fresh = {1: {"state": "open", "created_at": "2026-11-26T00:00:00Z"}}
        stale = {1: {"state": "open", "created_at": "2026-11-10T00:00:00Z"}}
        closed = {1: {"state": "closed", "created_at": "2026-11-26T00:00:00Z"}}
        self.assertTrue(recently_merged(pr, now, fresh))
        self.assertFalse(recently_merged(pr, now, stale))
        self.assertFalse(recently_merged(pr, now, closed))
        self.assertFalse(recently_merged({"merged_at": None}, now, fresh))

    def test_candidates_cover_open_and_recently_merged_bot_changes(self):
        api = API("unused", True)
        queries = []

        def fake_request(_path, _method, data):
            search = data["variables"]["search"]
            queries.append(search)
            if "author:app/n8n-cat-bot" in search and "is:open" in search:
                nodes = [
                    {"number": 44782, "author": {"login": "n8n-cat-bot"}, "files": {"nodes": [{"path": "pnpm-lock.yaml"}]}},
                    {"number": 45607, "author": {"login": "n8n-cat-bot"}, "files": {"nodes": [{"path": "packages/cli/src/a.ts"}]}},
                ]
            elif "author:app/n8n-cat-bot" in search and "is:merged" in search:
                nodes = [
                    {"number": 44010, "author": {"login": "n8n-cat-bot"}, "files": {"nodes": [{"path": "pnpm-lock.yaml"}]}},
                ]
            else:
                nodes = []
            return {"data": {"search": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}

        api._request = fake_request
        now = datetime.datetime(2026, 11, 27, tzinfo=datetime.timezone.utc)
        self.assertEqual(list(api.dependency_candidates(now)), [44782, 44010])
        self.assertTrue(any("is:merged merged:>=2026-11-17T00:00:00Z" in q for q in queries))

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
