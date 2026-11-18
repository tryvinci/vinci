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
