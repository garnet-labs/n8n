import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import github
import pr_context as context

REPO = "garnet-labs/n8n"
HEAD = "a" * 40


def pr(head=HEAD):
    return {"number": 1, "state": "open", "draft": False, "changed_files": 1,
            "head": {"sha": head, "repo": {"full_name": REPO}}}


class ContextTests(unittest.TestCase):
    def test_manual_current_head(self):
        with patch.object(context, "api", return_value=pr()):
            self.assertEqual(context.resolve(REPO, "workflow_dispatch", {"inputs": {"pr_number": "1"}}), ("1", HEAD))

    def test_invalid_manual_input(self):
        with self.assertRaises(ValueError):
            context.resolve(REPO, "workflow_dispatch", {"inputs": {"pr_number": "1;exit"}})

    def test_draft_reaches_policy_but_external_head_does_not(self):
        draft = {**pr(), "draft": True}
        with patch.object(context, "api", return_value=draft):
            self.assertEqual(context.resolve(REPO, "workflow_dispatch", {"inputs": {"pr_number": "1"}}), ("1", HEAD))
        external = pr()
        external["head"]["repo"]["full_name"] = "someone/n8n"
        with patch.object(context, "api", return_value=external):
            self.assertIsNone(context.resolve(REPO, "workflow_dispatch", {"inputs": {"pr_number": "1"}}))

    def test_recorder_resolution_empty_ambiguous_and_stale(self):
        event = {"workflow_run": {"name": "Garnet Runtime Visibility", "status": "completed",
                 "head_sha": HEAD, "path": ".github/workflows/garnet-record.yml", "repository": {"full_name": REPO}}}
        for candidates in [[], [pr(), pr()]]:
            with patch.object(context, "api", return_value=candidates):
                self.assertIsNone(context.resolve(REPO, "workflow_run", event))
        with patch.object(context, "api", side_effect=[[pr()], pr("b" * 40)]):
            self.assertIsNone(context.resolve(REPO, "workflow_run", event))
        with patch.object(context, "api", side_effect=[[pr()], pr()]):
            self.assertEqual(context.resolve(REPO, "workflow_run", event), ("1", HEAD))

    def test_other_workflow_is_ignored(self):
        event = {"workflow_run": {"name": "Other workflow"}}
        with patch.object(context, "api") as api:
            self.assertIsNone(context.resolve(REPO, "workflow_run", event))
            api.assert_not_called()

    def test_ready_comment_must_be_trusted_and_head_bound(self):
        event = {"issue": {"number": 1, "pull_request": {}}, "comment": {
            "user": {"login": "someone"}, "body": "<!-- garnet:summary {} -->"}}
        self.assertIsNone(context.resolve(REPO, "issue_comment", event))
        event["issue"]["pull_request"] = {"url": "https://example.invalid"}
        event["comment"] = {"user": {"login": context.BOT}, "body":
            '<!-- garnet:summary ' + json.dumps({"status": "finalized", "commit": HEAD}) + ' -->'}
        with patch.object(context, "api", return_value=pr()):
            self.assertEqual(context.resolve(REPO, "issue_comment", event), ("1", HEAD))

    def test_wait_requires_finalized_trusted_record(self):
        receipt = {"user": {"login": context.BOT}, "body": '<!-- garnet:summary ' + json.dumps(
            {"status": "finalized", "commit": HEAD}) + ' -->'}
        with patch.object(context, "api", side_effect=[pr(), [receipt]]):
            self.assertTrue(context.wait_record(REPO, "1", HEAD, timeout=0))
        with patch.object(context, "api", side_effect=[pr(), []]):
            with self.assertRaises(RuntimeError):
                context.wait_record(REPO, "1", HEAD, timeout=0)
        with patch.object(context, "api", return_value=pr("b" * 40)):
            self.assertFalse(context.wait_record(REPO, "1", HEAD, timeout=0))

    def test_publish_exact_marker_and_head(self):
        with patch.object(context, "api", side_effect=[pr(), [], pr(), {}]) as api:
            context.publish(REPO, "1", HEAD, {"head_sha": HEAD, "final_verdict": "APPROVED", "review_body": "Scoped review"})
        body = api.call_args.args[3]["body"]
        self.assertTrue(body.startswith("<!-- stamphog-sticky-review -->"))
        self.assertIn(f"reviewed `{HEAD}` — verdict: **APPROVED**", body)

    def test_stale_or_invalid_verdict_cannot_publish(self):
        with self.assertRaises(ValueError):
            context.publish(REPO, "1", HEAD, {"head_sha": "b" * 40})
        with self.assertRaises(ValueError):
            context.publish(REPO, "1", HEAD, {"head_sha": HEAD, "final_verdict": ""})
        with patch.object(context, "api", return_value=pr("b" * 40)) as api:
            with contextlib.redirect_stdout(io.StringIO()):
                context.publish(REPO, "1", HEAD, {"head_sha": HEAD, "final_verdict": "APPROVED"})
            self.assertEqual(api.call_count, 1)


class ApiDiffTests(unittest.TestCase):
    def test_api_file_stats_and_incomplete_list(self):
        item = {"filename": "package.json", "status": "modified", "additions": 1, "deletions": 1, "patch": "diff"}
        with patch.object(github, "_gh_api", side_effect=[[item], pr()]):
            self.assertEqual(github._api_diff_files(pr(), REPO)[0]["status"], "M")
        with patch.object(github, "_gh_api", return_value=[]):
            with self.assertRaises(RuntimeError):
                github._api_diff_files(pr(), REPO)
        empty = {**pr(), "changed_files": 0}
        with patch.object(github, "_gh_api", side_effect=[[], pr()]):
            self.assertEqual(github._api_diff_files(empty, REPO), [])
        with patch.object(github, "_gh_api", side_effect=[[item], pr("b" * 40)]):
            with self.assertRaises(RuntimeError):
                github._api_diff_files(pr(), REPO)

    def test_api_diff_pinned_pair_and_error(self):
        env = {"STAMPHOG_API_REVIEW": "1", "STAMPHOG_REPOSITORY": REPO}
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", env):
            dest = Path(directory) / "diff.patch"
            with patch.object(github.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "diff --git a/a b/a\n")) as run:
                github.write_pr_diff("b" * 40, HEAD, dest, Path(directory))
                self.assertIn(f"repos/{REPO}/compare/{'b' * 40}...{HEAD}", run.call_args.args[0])
                self.assertTrue(dest.read_text().startswith("diff --git"))
            with patch.object(github.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "gh")):
                with self.assertRaises(subprocess.CalledProcessError):
                    github.write_pr_diff("b" * 40, HEAD, dest, Path(directory))


if __name__ == "__main__":
    unittest.main()
