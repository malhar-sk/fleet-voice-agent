# STT model comparison (SYNTHETIC speech, CPU int8, 1 thread)

| Model | Clips | Decode | n | WER | CER | Lang ID (final) | Tool choice (rules, on these transcripts) | s/clip mean | s/clip p50 | s/clip max | Peak RSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| whisper-large-v3-turbo | mr | auto | 10 | 0.540 | 0.175 | 90% | 10/10 | 15.65 s | 15.60 s | 16.26 s | 1647 MB |
| whisper-large-v3-turbo | mr | forced_mr | 10 | 0.556 | 0.199 | 100% | 10/10 | 15.61 s | 15.47 s | 16.63 s | 1647 MB |
| whisper-medium | mr | auto | 10 | 0.508 | 0.206 | 80% | 10/10 | 12.65 s | 12.45 s | 14.39 s | 1580 MB |
| whisper-medium | mr | forced_mr | 10 | 0.508 | 0.206 | 100% | 10/10 | 12.08 s | 11.74 s | 14.02 s | 1580 MB |
| whisper-small | mr | auto | 10 | 0.603 | 0.236 | 80% | 8/10 | 4.39 s | 4.20 s | 4.89 s | 608 MB |
| whisper-small | mr | forced_mr | 10 | 0.587 | 0.239 | 100% | 8/10 | 4.24 s | 4.08 s | 4.87 s | 608 MB |
