"""A refused or failed Studio run shows its reason with one next step (COREPRODUC-692)."""

from __future__ import annotations

from ts_module import run_ts

MODULE = "apps/studio/app/ui/plain-text.ts"
NAMES = ["runProblem"]


def test_the_status_or_the_reason_picks_the_button() -> None:
    body = """
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(m + ": " + JSON.stringify(a)); };
const http = (status, detail) => Object.assign(new Error(detail), { status });
const credits = "This run needs up to 8 credits, and you have 0. Add credits, then run it again.";
eq(runProblem(http(402, credits)), { text: credits, action: "credits" }, "402: not enough Vinci credits");
eq(runProblem(http(403, "Studio generation is not available for free users. Please upgrade to a paid plan.")).action, "upgrade", "403: free plan");
eq(runProblem(http(400, "Sign in to Higgsfield in Connect to run nano_banana_pro.")).action, "connect", "400: not signed in");
eq(runProblem(http(429, "Another run is starting. Try again in a few seconds.")), { text: "Another run is starting. Try again in a few seconds." }, "429: no button");
eq(runProblem("Magnific refused the request: not enough credits. Vinci charged nothing.").action, "connect", "provider refusal");
eq(runProblem("Your Wavespeed key was removed. Add it in Connect, then run this again.").action, "connect", "key removed");
eq(runProblem("Your Higgsfield sign-in ended. Sign in again in Connect. Vinci charged nothing.").action, "connect", "sign-in ended");
eq(runProblem("The model did not finish in 30 minutes. Nothing was charged."), { text: "The model did not finish in 30 minutes. Nothing was charged." }, "timeout: no button");
eq(runProblem(new Error("Failed to fetch")), { text: "Could not reach Vinci. Check your connection, then try again." }, "network: plain text, no button");
eq(runProblem("").action, undefined, "a failed run with no reason: the generic text, no Connect button");
"""
    result = run_ts(MODULE, NAMES, body)
    assert result.returncode == 0, result.stderr  # run_ts does not check: a thrown assertion fails here


def test_a_run_that_waits_says_its_price_and_limit() -> None:
    """A run over a spend limit shows the price and the limit in plain words (COREPRODUC-786)."""
    body = """
const eq = (a, b) => { if (a !== b) throw new Error(JSON.stringify(a)); };
eq(approvalReason({ estimate: { total: 0.08 }, awaiting_reason: "estimate 0.08 exceeds --max-cost 0.01" }), "$0.080 is over your max cost of $0.010");
eq(approvalReason({ estimate: { total: 0.5 }, awaiting_reason: "estimate 0.5 would exceed monthly cap 10" }), "$0.500 is over your monthly cap of $10.000");
eq(approvalReason({ estimate: { total: 2 }, awaiting_reason: "estimate 2 exceeds require_approval_over 1" }), "$2.000 is over your approval limit of $1.000");
eq(approvalReason({ estimate: { total: 0.08 }, awaiting_reason: "something new" }), "$0.080");
"""
    result = run_ts(MODULE, ["approvalReason"], body)
    assert result.returncode == 0, result.stderr
