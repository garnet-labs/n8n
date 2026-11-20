# Review policy

The review engine and merge-gate relay are vendored from garnet-labs/posthog
at aee1db6. The ownership resolver is from garnet-labs/garnet-runtime-review-reference.
Their MIT attribution is retained in tools/pr-approval-agent/VENDOR-NOTICE.md.

The existing Garnet recorder is unchanged: it records `pnpm install
--frozen-lockfile` using tokenless OIDC. Garnet records; this repository's
review policy decides. The merge-gate relay posts the App's scoped outcome,
not a merge authorization or a branch-protection check.

Both workflows run from the default branch on completion of the
`Garnet Runtime Visibility` recorder, or by manual dispatch with `pr_number`.
They resolve the PR by the recorder's exact head SHA and skip stale or ambiguous
heads. They wait up to 15 minutes for the finalized, head-bound App record;
the App's comment event also retriggers them when publication finishes later.
No label is required or changed. Same-repository open PRs are eligible; draft
status is evaluated by the review policy, not silently skipped by the resolver.
Trusted engine and policy are checked out from master, never the PR head or its chosen base.
The org-level `ANTHROPIC_API_KEY` enables LLM review. The workflow publishes
`<!-- stamphog-sticky-review -->` with a full-head verdict line.

The reviewer consumes the API's file list and SHA-pinned comparison diff.
PR commits are fetched only for read-only manifest/provenance/history inspection;
they are never checked out or executed. The LLM has only Read/Grep/Glob tools.
The publisher rejects a verdict whose head differs from either the resolved
head or the PR's current head. The workflows and policy need not be in the PR tree.

Package manifests, workspace configuration and lockfiles require dependency
review. Usable head-bound runtime evidence can clear that deterministic deny
for further LLM review; it is never automatic approval or proof of completeness.
There is no configured CI attestation bypass. The vendored ownership resolver
reads owners.yaml/product.yaml, not n8n's CODEOWNERS; absent ownership is unknown,
not owning-team assurance.

No automatic merge is configured. Required checks and reviewer installation
are separate repository settings. Policy/engine changes require human review.
