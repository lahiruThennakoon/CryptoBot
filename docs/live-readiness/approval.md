# Live-Trading Approval Checklist — Owner Sign-off

> This document is the final, human gate. Nothing in the codebase can enable
> live trading; only completing this checklist AND performing the multi-step
> configuration in `deployment-rollback.md §2` does. Signing this document
> acknowledges that **no profit is guaranteed and allocated capital may be
> lost entirely.**

## Preconditions (all must be checked with evidence attached)

- [ ] `cryptobot readiness` exits 0 (output archived, dated)
- [ ] Security checklist S1–S13 complete (`security-reliability-checklists.md`)
- [ ] Reliability drills R1–R10 complete with recorded evidence
- [ ] Performance evidence complete per `performance-evidence.md` (GC-1…GC-6)
- [ ] Zero unresolved critical/high defects (GC-7)
- [ ] Known limitations and unresolved risks read and accepted (GC-9/§4–5)
- [ ] Local legal, tax, and regulatory obligations verified by the owner
- [ ] Capital allocation decided: ______ USDT — an amount the owner can
      afford to lose entirely
- [ ] Live loss limits configured: max daily loss ______ , max order value ______
- [ ] Monitoring plan for the first 48 hours agreed

## Decision

| Field | Value |
|-------|-------|
| Decision | APPROVE LIVE / REMAIN IN PAPER |
| Owner name | |
| Date | |
| Release tag | |
| Config version hash | |
| Signature | |

## Standing rules after any approval

- Any risk-limit halt → trading stops; resumption requires this owner's
  explicit review acknowledgment.
- Any critical defect, reconciliation mismatch, or severe drift alert →
  revert to paper mode pending investigation.
- This approval expires after 90 days or any major code change to the
  execution/risk path, whichever comes first; re-run the review to renew.

> Reminder embedded in every report this system produces: cryptocurrency
> trading is highly risky; historical and paper performance do not guarantee
> future results; losing days and periods are expected.
