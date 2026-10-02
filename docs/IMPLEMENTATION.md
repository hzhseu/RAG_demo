# Implementation ledger

Authority: user-approved 离线 Windows PPT 知识库与聊天 Demo 实施计划, 2026-10-01.

## Work items
1. Portable package, PPTX extraction/chunking, hybrid retrieval; tests first.
2. Real external adapters and resumable builder/CLI.
3. Local API, streaming/cancel, sessions, labels/export.
4. React browser UI with local PDF.js.
5. Fixtures, packaging, dependency provisioning and acceptance reports.

## Decisions
- Empty non-git directory: implement directly in the user-specified workspace; there is no branch to isolate.
- Keep external engines behind interfaces so deterministic tests don't impersonate actual Qwen/OCR acceptance.
- Initial environment has no models, LibreOffice or PaddleOCR. Report real-engine and clean-machine validation separately.
- Full-file hashes are used for document identity. Build cache includes parser/OCR/converter configuration.
- Fail closed on unsupported/corrupt packages and missing runtime assets; no silent fake model fallback.

## Verification
- Core/API regression suite: 30 passing; includes Windows process-tree timeout, cancel during embedding, export 416 cleanup, UTF-8 roundtrip, merged cells, page context with table year, ambiguous ZIP paths, checksummed payload integrity, per-document topic synthesis, abandoned workspace cleanup and real PPTX extraction.
- React TypeScript and Vite production build pass. Playwright headless Edge smoke passes: chat, citation panel, labels, responsive layout. This first browser test uses an explicitly test-only engine.
- Real Qwen CPU chat and embedding smoke pass. Real PaddleOCR reads bilingual screenshot with 4 hours and 99.5% correctly.
- Ruling: Paddle oneDNN failed with PIR attribute conversion; use enable_mkldnn=False. Actual inference then succeeded.
- Ruling: LibreOffice defaults auto-update and changed deployed binaries during initial smoke. Re-extracted fixed 25.8.2.2 and disabled update defaults before first launch; adapter also sets profile-level disable flags.
- Read-only independent review found cancellation/integrity/export/cleanup/portable-filesystem issues; regressions added and fixed. Further review found descendant pipe timeout; real Windows regression now passes.
- Final real 2-deck/6-slide build: 9 chunks, 71.11s build phase. Real multilingual retrieval Recall@8 12/12. Five real Qwen answers inspected against sources (numeric table, screenshot, historical/current warranty, no answer, prompt injection).
- 40-deck/400-slide structural parser test passes (external OCR substituted, explicitly not full inference benchmark).
- Full real-engine scale run through the portable EXE: 30 decks/90 slides, 93 chunks, zero failed/excluded, 659.60s wall time, 7414 MiB peak process-tree RSS. One image page and repeated synthetic subject matter; not a real-corpus quality benchmark.
- Complete portable EXE package created, EXE scan/doctor pass. Packaged browser smoke passes with real Qwen and pixel-verified PDF rendering, using a PATH without developer tools.
- Final EXE ingestion with developer PATH removed passes: 2 decks/6 slides, 131.40s including component checks. Processing/model manifest fields and content-free event logs verified. Microsoft VC14 14.51.36247.0 staged app-locally and actual DLL mappings verified.
- Bundled Noto CJK and LibreOffice fonts use the Windows private font folder; PDF embedding and Chinese text extraction verified.
- Rotating local logs contain fixed event names, counts and exception types, excluding document contents, questions and answers.
- Ruling: initial 4B topic synthesis overinterpreted missing information and historical policy as conflicts. Tightened prompts to explicit facts/dates/units only, tested real synthesis again, and inspected corrected content. This does not replace real-corpus faithfulness acceptance.
- Clean Windows and real customer document acceptance remain separate, not claimed complete.
