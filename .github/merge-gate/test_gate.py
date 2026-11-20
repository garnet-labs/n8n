import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import gate
import gates
import gate_profile
import runtime_evidence
from policy import load_policy, PolicyError


HEAD = "a" * 40
ROOT = Path(__file__).resolve().parents[2]


class MergeGateTests(unittest.TestCase):
    def summary(self, **overrides):
        return dict(status="finalized", commit=HEAD, capture_quality="complete",
                    incomplete=0, outcome="unchanged", **overrides)

    def test_complete_record(self):
        summary = self.summary()
        self.assertEqual(gate.decide(summary, gate.evidence_gaps(summary, HEAD), []), "NOTHING NEW")

    def test_stale_pending_and_incomplete_are_undeterminable(self):
        for field, value in [("commit", "b" * 40), ("status", "pending"),
                             ("capture_quality", "best-effort"), ("incomplete", 1)]:
            summary = self.summary()
            summary[field] = value
            self.assertEqual(gate.decide(summary, gate.evidence_gaps(summary, HEAD), []), "UNDETERMINABLE")

    def test_empty_and_malformed_marker(self):
        for body in ["", "<!-- garnet:summary {bad} -->", "<!-- garnet:summary [] -->"]:
            self.assertIsNone(gate.parse_summary(body))

    def test_changed_destination_and_chain(self):
        body = """<details><summary><b>Dependency install</b></summary>
```diff
 pnpm
+└─ registry[.]npmjs[.]org
```
</details>"""
        changes = gate.changed_destinations(body)
        self.assertEqual(changes, [{"job": "Dependency install", "destination": "registry.npmjs.org", "chain": ["pnpm"]}])
        summary = self.summary()
        summary.update(outcome="changed", capture_quality="best-effort")
        gaps = gate.evidence_gaps(summary, HEAD)
        self.assertEqual(gate.decide(summary, gaps, changes), "CHANGED")
        rendered = gate.render(summary, "CHANGED", gaps, changes, HEAD, ["pnpm-lock.yaml"])
        self.assertIn("registry.npmjs.org", rendered)
        self.assertIn("pnpm", rendered)
        self.assertIn("Evidence gaps", rendered)

    def test_fixture_main_posts_head_bound_receipt(self):
        body = "<!-- garnet:summary " + json.dumps(self.summary()) + " -->"
        calls = []

        def gh(method, path, fields=None):
            calls.append((method, path, fields))
            if method == "POST":
                return {}
            if "/comments" in path:
                return [{"user": {"login": gate.BOT}, "body": body}]
            if "/files" in path:
                return [{"filename": "pnpm-lock.yaml"}]
            return {"head": {"sha": HEAD}}

        with patch.object(gate, "gh", side_effect=gh), patch.object(sys, "argv", ["gate.py", "garnet-labs/n8n", "1"]):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                gate.main()
        self.assertIn("NOTHING NEW for garnet-labs/n8n#1", output.getvalue())
        self.assertIn("Merge gate: **NOTHING NEW**", calls[-1][2]["body"])

    def test_missing_comment_does_not_publish(self):
        with patch.object(gate, "gh", side_effect=[{"head": {"sha": HEAD}}, []]) as gh:
            with patch.object(sys, "argv", ["gate.py", "garnet-labs/n8n", "1"]), contextlib.redirect_stdout(io.StringIO()):
                gate.main()
        self.assertEqual(gh.call_count, 2)


class N8nPolicyTests(unittest.TestCase):
    def test_dependency_paths(self):
        for path in ["pnpm-lock.yaml", "pnpm-workspace.yaml", "packages/foo/pnpm-lock.yaml"]:
            self.assertIn("deps_toolchain", gates.detect_deny_categories([path]))
        self.assertTrue(gates.has_dependency_changes(["packages/foo/package.json"]))
        self.assertEqual(gates.detect_deny_categories([]), [])

    def test_policy_engine_and_recorder_are_guarded(self):
        for path in [".stamphog/policy.yml", ".github/merge-gate/gate.py", "tools/pr-approval-agent/gates.py"]:
            self.assertIn("stamphog_policy", gates.detect_deny_categories([path]))
        self.assertIn("infra_cicd", gates.detect_deny_categories([".github/workflows/garnet-record.yml"]))

    def test_runtime_policy_loads(self):
        evidence = runtime_evidence.load_config(ROOT / ".stamphog")
        profile = gate_profile.load_config(ROOT / ".stamphog")
        self.assertIsNotNone(evidence)
        self.assertIsNotNone(profile)

    def test_missing_policy_fails_closed(self):
        with self.assertRaises(PolicyError):
            load_policy(ROOT / ".stamphog/missing.yml", lockfile_names=gates._ALL_LOCKFILE_NAMES,
                        ownership_formats=gates.OWNERSHIP_FORMAT_LOCATORS)

    def test_workflow_contract(self):
        workflow = (ROOT / ".github/workflows/pr-approval-agent.yml").read_text()
        publisher = (ROOT / ".github/merge-gate/pr_context.py").read_text()
        self.assertIn('MARKER = "<!-- stamphog-sticky-review -->"', publisher)
        self.assertIn('— verdict: **{outcome}**', publisher)
        self.assertIn('ref: master', workflow)
        self.assertIn('secrets.ANTHROPIC_API_KEY }}', workflow)
        self.assertIn('workflow_run:', workflow)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('pull_request:', workflow)
        recorder = (ROOT / ".github/workflows/garnet-record.yml").read_text()
        self.assertIn('id-token: write', recorder)
        self.assertIn('contents: read', recorder)
        self.assertNotIn('api_token', recorder)
        self.assertNotIn('GARNET_API_TOKEN', recorder)


if __name__ == "__main__":
    unittest.main()
