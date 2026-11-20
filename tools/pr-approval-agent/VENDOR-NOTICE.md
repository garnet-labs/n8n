# Attribution

The review engine and policy originate in PostHog's MIT-licensed StampHog
engine, as adapted in garnet-labs/posthog at
`aee1db69f6a10196dacd03f15721cf6e4df6b072`.
The ownership resolver is vendored from garnet-labs/garnet-runtime-review-reference
at `d6737ffcbb897ccf18b6f5954e98d5008451c34a`.
Copyright (c) PostHog. Copyright (c) 2026 Garnet Labs.

The policy, steering and workflows are adapted for this pnpm repository;
github.py adds an opt-in API file-list and pinned-comparison-diff mode. The
remaining production review engine is unchanged. Its policy tests reflect the
n8n configuration. The merge-gate relay wording is comparison-scope neutral,
with current-head guards before publication.

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
