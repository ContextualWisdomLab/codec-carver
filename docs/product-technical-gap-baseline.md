# codec-carver product and technical gap baseline

This snapshot binds current gaps to exact evidence. It is not merge
authorization; current-head Checks and independent review remain required.

| Gap ID | Status | Exact evidence | Owner and acceptance |
|---|---|---|---|
| SECURITY-DEPENDENCY-HTTPX2-01 | Proposed — source repaired; owner revalidation required | `codec-carver#651@21950a764a6e59483b1792199360bb20bb46e542`, Security Scan `36608104327`, job `109720869095`: four fixable `httpx2==2.5.0` CVEs | `codec-carver#668` removes the unused fork from all manifests and adds a three-manifest regression contract. Accept after exact-head Security, CI, SAST, fuzz, and non-skipped CodeQL plus independent review. |

## Product and technical effect

The codec-carving, upload, MCP, and transcript-search contracts are unchanged.
The repair only removes an unused development compatibility fork, reducing
supply-chain exposure without adding a replacement dependency or a parallel
implementation.
