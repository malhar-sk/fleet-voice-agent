### Voice run: Claude (claude-haiku-5-5 via claude CLI)

File: `evals/results/voice_claude_cli.jsonl`

| Group | n | WER | CER | Lang ID | Tool choice | Tool + args | Answer correct | V2V p50 | V2V p95 | STT p50 | LLM p50 | TTS first p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| English | 10 | 0.000 | 0.000 | 100% | 100% | 100% | 100% | 8.12 s | 9.37 s | 3.65 s | 4.24 s | 0.27 s |
| Hindi | 10 | 0.338 | 0.117 | 100% | 100% | 100% | 100% | 7.46 s | 9.36 s | 4.07 s | 3.19 s | 0.17 s |
| Marathi | 10 | 0.603 | 0.236 | 80% | 90% | 90% | 90% | 8.19 s | 9.45 s | 4.24 s | 3.70 s | 0.23 s |
| **All clean (30)** | 30 | 0.282 | 0.109 | 93% | 97% | 97% | 97% | 8.02 s | 9.72 s | 4.00 s | 3.56 s | 0.23 s |
| Noisy variants (5) | 5 | 0.367 | 0.129 | 100% | 100% | 100% | 100% | 7.42 s | 8.44 s | 4.00 s | 3.39 s | 0.20 s |
| All (35) | 35 | 0.292 | 0.111 | 94% | 97% | 97% | 97% | 7.98 s | 9.66 s | 4.00 s | 3.45 s | 0.23 s |

Key-fact re-scored with the current checker: 2 verdict(s) differ from the run-time score (run-time answer-correct, all 35: 32/35).

### Voice run: offline rules router (no LLM)

File: `evals/results/voice_rules.jsonl`

| Group | n | WER | CER | Lang ID | Tool choice | Tool + args | Answer correct | V2V p50 | V2V p95 | STT p50 | LLM p50 | TTS first p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| English | 10 | 0.000 | 0.000 | 100% | 100% | 100% | 100% | 4.54 s | 5.49 s | 4.09 s | 0.00 s | 0.48 s |
| Hindi | 10 | 0.338 | 0.117 | 100% | 90% | 90% | 90% | 5.23 s | 6.55 s | 4.86 s | 0.00 s | 0.53 s |
| Marathi | 10 | 0.603 | 0.236 | 80% | 80% | 80% | 80% | 5.17 s | 6.32 s | 4.58 s | 0.00 s | 0.59 s |
| **All clean (30)** | 30 | 0.282 | 0.109 | 93% | 90% | 90% | 90% | 5.11 s | 6.55 s | 4.47 s | 0.00 s | 0.54 s |
| Noisy variants (5) | 5 | 0.367 | 0.129 | 100% | 100% | 100% | 100% | 4.84 s | 5.34 s | 4.17 s | 0.00 s | 0.66 s |
| All (35) | 35 | 0.292 | 0.111 | 94% | 91% | 91% | 91% | 5.09 s | 6.52 s | 4.45 s | 0.00 s | 0.55 s |

Key-fact re-scored with the current checker: 0 verdict(s) differ from the run-time score (run-time answer-correct, all 35: 32/35).

### Text-only (oracle transcripts = the script), Claude via CLI

File: `evals/results/text_claude_cli.jsonl`

| Group | n | Tool choice | Tool + args | Answer correct | LLM p50 | LLM p95 |
|---|---|---|---|---|---|---|
| English | 10 | 100% | 100% | 100% | 3.19 s | 4.48 s |
| Hindi | 10 | 100% | 100% | 100% | 3.35 s | 4.75 s |
| Marathi | 10 | 100% | 100% | 90% | 4.11 s | 4.69 s |
| **All clean (30)** | 30 | 100% | 100% | 97% | 3.46 s | 4.75 s |

### Rules router on the same Whisper transcripts as the Claude voice run

File: `evals/results/transcripts_rules.jsonl`

| Group | n | Tool choice | Tool + args | Answer correct | LLM p50 | LLM p95 |
|---|---|---|---|---|---|---|
| English | 10 | 100% | 100% | 100% | 0.00 s | 0.00 s |
| Hindi | 10 | 70% | 70% | 70% | 0.00 s | 0.00 s |
| Marathi | 10 | 60% | 60% | 50% | 0.00 s | 0.00 s |
| **All clean (30)** | 30 | 77% | 77% | 73% | 0.00 s | 0.00 s |

### Rules router + fuzzy keyword match (added AFTER seeing the row above: optimistic)

File: `evals/results/transcripts_rules_fuzzy.jsonl`

| Group | n | Tool choice | Tool + args | Answer correct | LLM p50 | LLM p95 |
|---|---|---|---|---|---|---|
| English | 10 | 100% | 100% | 100% | 0.00 s | 0.00 s |
| Hindi | 10 | 90% | 90% | 90% | 0.00 s | 0.00 s |
| Marathi | 10 | 80% | 80% | 80% | 0.00 s | 0.00 s |
| **All clean (30)** | 30 | 90% | 90% | 90% | 0.00 s | 0.00 s |

### Voice-to-voice over WebRTC (client-measured)

| Path | n | V2V p50 | V2V p95 | server-side p50 (from VAD stop) |
|---|---|---|---|---|
| Browser-equivalent WebRTC client (aiortc → Pipecat SmallWebRTC) | 9 | 8.78 s | 10.48 s | 8.32 s |
