# User acceptance and release workflow

- After implementing a change, build and test it, then launch one local application for the user to review. Default to the C++ edition. Use an isolated profile for acceptance unless the user asks to use existing data. Include local visual previews when appropriate.
- Wait for the user to explicitly accept the result before committing, pushing, changing the release version, triggering publication workflows, or publishing a release. A request to implement or revise a feature is not acceptance.
- After the user accepts and authorizes release, update the applicable versions, commit and push to GitHub, verify the required CI builds succeed, then publish using the repository release workflow. Report any failed check without publishing an unverified release.

# Performance and interaction quality

- Treat responsiveness as part of feature correctness. Session switching, scrolling, animations, input, and opening Widgets must remain responsive with large real histories, not only empty demo data.
- Profile before optimizing. Compare cold and repeated navigation on the same data, record latency and UI stalls, and check memory/cache bounds. Distinguish offscreen measurements from actual display behavior; do not claim gains without a comparable baseline.
- Keep transcript I/O and expensive preparation off the GUI thread. Create rich QML content incrementally near the viewport; prioritize every visible message, including after scrolling stops. Use bounded caches with explicit invalidation and eviction, and retain recent layouts and scroll positions where useful.
- Keep animations independent of content loading. Do not feed transient model-reset positions into animations, restore navigation on ordinary page completion, or repeatedly discard and recreate controls at viewport edges. Test rapid switching, fast scroll reversals, idle completion, and stable edge rendering.
- Avoid redundant persistence and credential-store access during navigation. Write secrets only when they change, coalesce ordinary settings saves, and preserve historical data and drafts through optimization and acceptance testing.
- Acceptance previews must use a prepared Pi/runtime bridge matching the tested source. Verify representative right-sidebar Widgets as well as chat interactions; a stale shared runtime is not an acceptable preview or a reason to dismiss a timeout.
