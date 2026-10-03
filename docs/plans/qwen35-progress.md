# Qwen3.5 implementation ledger

Plan: user-approved Qwen3.5-4B upgrade, shared registry, model switching, build/cache separation, dual-model offline packaging.

Tasks: 1 registry/runtime; 2 actual model validation; 3 RAG switch/session isolation; 4 builder/cache/tester; 5 packaging and acceptance.

Ruling: isolated native worktree; reuse existing runtime by absolute configuration during development, package into original project dist with backups. No existing model/KB deletion.
Preflight interfaces: shared registry produces immutable per-model chat configuration; embedding configuration remains original. API operation lock serializes switches and generation; model sequence rejects stale pages. Parsing signature excludes all chat assets; generation signature includes full profile and prompts.
Task 1 baseline: sandbox run blocked by Windows temporary-directory permissions; unsandboxed baseline passed 116 tests.

Task 1: registry and runtime implemented; baseline116 and expanded128 tests passed. Registry new default qwen35-4b, legacy default retained.
Task 2: complete: GGUF SHA256 verified, b11326 loads new architecture, template thinking=false and real Chinese streaming successful. No second engine required.
Task 3: implemented API model switching/sequence/session identities and browser UI. Actual EXE switch, old KB question, preview and session restore passed so far; full smoke ongoing.
Task 4: implemented builder --model, interactive selection, shared tester config, parse-v2/generation-v2 cache; cross-model parse reuse test passed.
Task 5: main/builder/tester EXEs built in worktree; independent whole-change review ongoing; original delivery still untouched.
Ruling: cached prompt identity uses explicit PROMPT_REVISION and SYSTEM rather than reading Python source at runtime, because frozen modules do not ship source paths; future prompt edits must bump revision.
Ruling: offline browser verification aborts all non-loopback HTTP requests and inspects external requests; no system-wide network adapter/firewall changes. This verifies browser offline operation, not a physically disconnected clean Windows machine.

Final review: fresh-context reviewer found 3 Important issues. All fixed with failing regressions then green suite: persistence+rollback failure now fails closed and invalidates model sequence; custom catalogs migrate weights and full engine directories; generation identity fingerprints engine executable plus adjacent DLLs.
Final: reviewer small-context topic finding regraded Important because future selectable profiles must work; failing test added, budgets corrected, suite green.
Final: ledger-progress note resolved by recording evidence here. No deferred review findings.
Task 5: first packaged main browser smoke passed actual dual-model questions, followup, switch, stale request, old-session resume, PDF preview, topic and model-tagged export with external browser HTTP blocked. Final repaired EXEs being rebuilt. Tester first smoke exposed whitespace variation in remembered code; assertion now accepts the same code with optional whitespace.

Final: new-session persistence is included in switch transaction; failing test then green suite135.
Task 5: tester final EXE browser passed; main repaired EXE browser passed; both real builder EXEs produced successful one-page KBs. Byte-identical embedding arrays verified, one parse cache entry and two generation entries verified.
Ruling: deliver tested source changes into the original clean checkout as uncommitted edits, preserving a source snapshot and prior EXE directories; no Git merge, remote push or publication is part of this task.

Task 5: final main EXE after transactional session fix passed complete browser smoke again. All135 Python and5 frontend tests green; actual tester and builder acceptance green. Delivery copy and checksum validation next.

Task 5: complete. Original checkout tests135/135 and frontend5/5 passed. Original delivery installed and verified: NordRAG36121 files; ModelTester206 files. Installed-path EXE clean-PATH launch and qwen35→default→qwen35 switches with new sessions passed. Previous releases and source snapshot are recorded in artifacts/qwen35-delivery.json. No Git commit or remote publication performed.
