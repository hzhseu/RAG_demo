# Offline reranking implementation ledger

Approved scope: Qwen3-Reranker-0.6B Q8_0, existing llama.cpp b11326,
30 candidates / 8 final passages, default enabled with session-bound switch,
explicit fallback, cancellation, real A/B validation, complete portable package.

- Workspace: existing clean checkout reused on `codex/offline-reranking` so the
  installed runtime, models, build tools and previous deliveries remain available.
- Model source: ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF;
  revision a02f48bb4f057028298c21fa033da2b30d7742d5;
  SHA256 22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48.
- Tasks: (1) real compatibility probe; (2) retrieval/runtime tests and implementation;
  (3) session/UI integration; (4) real A/B and regression; (5) review and packaging.
- Interface: existing `retrieve` retains baseline behavior; a new retrieval
  coordinator returns evidence plus fixed diagnostic metadata. Optional reranker
  assets are validated independently from mandatory embedding/chat components.
- No commits or publishing requested. Keep source changes reviewable in the checkout.

## Verification and decisions

- Real b11326 probe: HTTP 200 with finite, differentiated relevance scores; correct
  warranty passage precedes distractors. Model SHA256 verified after download.
- Retrieval/API/config tests were observed failing before corresponding implementation.
- 213 Python tests passed; 5 frontend API tests passed; TypeScript and Vite passed.
- Rerank UI test passed default/toggle/history/chat mode/model/knowledge restore and
  visible fallback. Existing advanced UI regression passed on a reset test harness.
- Ruling: browser tests await UI completion instead of `Response.finished()` for SSE;
  the latter did not resolve despite a saved completed response. Existing advanced UI
  test now waits for document hydration before checking the count.
- Real 12-question comparison: both modes Recall@8=1 and MRR@8=1, no regression.
  First rerank 5.55s; warm mean 3.875s on 9-chunk artificial library. Four independent
  multilingual/numeric/year distractor cases passed. Not business-data validation.
- Independent read-only reviewer reported no actionable high/medium findings.
- Windows sandbox temp-directory ACLs prevented pytest/package-extraction checks;
  reran those commands with normal permissions within the project artifacts directory.
- Final full suite: 215 passed in 10.66s. TypeScript/Vite and 5 frontend API tests passed.
- Real long-input scoring preserved 372029-character original evidence; actual cancellation
  and deadline expiry stopped the owned server. Packaged real-model/browser acceptance
  and `kb-builder.exe doctor` passed. No non-local browser requests or JS errors.
- Complete portable folder: 36131 checksummed files, 8.507 GiB; two previous knowledge
  files verified by content hash in the new package. Previous release preserved at
  `dist/previous-releases/NordRAG-20261005-213208-10d4f7c9`.
