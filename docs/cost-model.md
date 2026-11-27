# Cost model

Estimates always come from the catalog snapshot in the lockfile. A provider price change never silently changes an estimate; refresh is an explicit reviewed diff.

1. Pre-run estimate
2. Budgets (`--max-cost`, monthly caps, `require_approval_over`) → `awaiting_approval` when over; the person approves or cancels the run on the Studio's Cost report page (`#cost/<run_id>`) or with `vinci jobs approve <run_id>`
3. Immutable receipts
4. Cheapest compatible route by default; pins recorded in the run manifest
5. CAS + idempotency: identical node re-run costs $0 and says so on the receipt

Vinci is not "always cheaper than Magnific." The wedge is transparency, portability, and a $0 monthly floor.
