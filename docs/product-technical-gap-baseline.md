# codec-carver product and technical gap baseline

This snapshot binds current gaps to exact evidence. It is not merge
authorization; current-head Checks and independent review remain required.

| Gap ID | Status | Exact evidence | Owner and acceptance |
|---|---|---|---|
| SECURITY-DEPENDENCY-HTTPX2-01 | Proposed — source repaired; owner revalidation required | `codec-carver#651@21950a764a6e59483b1792199360bb20bb46e542`, Security Scan `36608104327`, job `109720869095`: four fixable `httpx2==2.5.0` CVEs | `codec-carver#668` removes the unused fork from all manifests and adds a three-manifest regression contract. Accept after exact-head Security, CI, SAST, fuzz, and non-skipped CodeQL plus independent review. |
| SECURITY-DEPENDENCY-HTTPX2-02 | Proposed — canonical owner integrated; consumer revalidation required | `codec-carver#659@b07a37febd3d93362dc0312277b93b76260112d1`, Security Scan `36605582265`, job `109712219959`: the same four fixable `httpx2==2.5.0` CVEs | #659 ordinary-merges `codec-carver#668@4f2b97e7fb30f5602bf0f697077fea4ed3ffddff` while preserving the HMAC type-safety delta as the other parent. Apply the same acceptance gates. |

## Product and technical effect

The codec-carving, upload, MCP, and transcript-search contracts are unchanged.
The repair only removes an unused development compatibility fork, reducing
supply-chain exposure without adding a replacement dependency or a parallel
implementation.
