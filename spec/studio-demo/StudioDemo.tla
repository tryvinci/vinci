---- MODULE StudioDemo ----
EXTENDS TLC
\* Models the Studio demo-mode catalog visibility flow from
\* apps/studio/lib/model-search.ts (studioVisible) and apps/daemon/vinci_daemon/studio.html.
\* FilterOld = TRUE models the pre-fix filter (m.provider /= "mock");
\* FilterOld = FALSE models the fix (keep mock when the daemon marks it available).
CONSTANT FilterOld

\* Demo catalog as served by GET /models after `init --demo`:
\* the three mock practice models are enabled and marked available = TRUE;
\* real catalog models are present but available = FALSE (no keys, live spend off).
DemoCatalog ==
  { [provider |-> "mock",      available |-> TRUE]
  , [provider |-> "fal",       available |-> FALSE]
  , [provider |-> "wavespeed", available |-> FALSE] }

\* Non-demo catalog: same models, but mock is not enabled -> available = FALSE.
NormalCatalog ==
  { [provider |-> "mock",      available |-> FALSE]
  , [provider |-> "fal",       available |-> FALSE]
  , [provider |-> "wavespeed", available |-> FALSE] }

Visible(m) ==
  IF FilterOld THEN m.provider /= "mock"
  ELSE m.provider /= "mock" \/ m.available = TRUE

\* studio.html usable(): mock is always usable; other providers need
\* available AND live spend, which is off in a fresh demo.
Usable(m) == m.provider = "mock" \/ m.available = TRUE

Picker(catalog) == {m \in catalog : Visible(m)}

\* The advertised demo promise (README: "The full Studio runs in demo mode
\* with practice providers at $0. Every feature works."): the Studio picker
\* must offer at least one model the user can actually run at $0.
DemoPickerHasUsableModel == \E m \in Picker(DemoCatalog) : Usable(m)

\* Non-demo behavior must stay unchanged: no mock rows in the picker.
NormalPickerHidesMock == \A m \in Picker(NormalCatalog) : m.provider /= "mock"
====
