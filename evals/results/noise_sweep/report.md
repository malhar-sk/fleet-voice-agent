# Noise sweep (SYNTHETIC speech + generated noise)

{"started": "2026-11-23T12:14:18Z", "stt": {"model": "whisper-small", "threads": 1, "prompt": true, "mr_ratio": 0.0, "en_min": 0.5, "max_tokens": 96}, "n_clips": 210, "command": "python -m evals.noise_sweep --claude", "claude": {"model": "claude-haiku-5-5", "plan_calls": 90, "cache_hits": 52, "new_llm_calls": 38}, "finished": "2026-11-23T12:31:19Z"}

| Noise | SNR | Lang | n | WER | CER | Lang ID | Tool choice (rules) | Tool+args (rules) | Tool choice (Claude) | Tool+args (Claude) |
|---|---|---|---|---|---|---|---|---|---|---|
| clean | clean | English | 10 | 0.000 | 0.000 | 100% | 100% | 100% | 100% | 100% |
| clean | clean | Hindi | 10 | 0.338 | 0.117 | 100% | 90% | 90% | 100% | 100% |
| clean | clean | Marathi | 10 | 0.603 | 0.236 | 80% | 80% | 80% | 90% | 90% |
| clean | clean | **All** | 30 | 0.282 | 0.109 | 93% | 90% | 90% | 97% | 97% |
| white | 20 dB | English | 10 | 0.000 | 0.000 | 100% | 100% | 100% | not run | not run |
| white | 20 dB | Hindi | 10 | 0.394 | 0.143 | 100% | 80% | 80% | not run | not run |
| white | 20 dB | Marathi | 10 | 0.746 | 0.340 | 80% | 90% | 80% | not run | not run |
| white | 20 dB | **All** | 30 | 0.341 | 0.149 | 93% | 90% | 87% | not run | not run |
| white | 10 dB | English | 10 | 0.000 | 0.000 | 100% | 100% | 100% | 100% | 100% |
| white | 10 dB | Hindi | 10 | 0.423 | 0.197 | 100% | 60% | 60% | 100% | 100% |
| white | 10 dB | Marathi | 10 | 0.810 | 0.442 | 70% | 70% | 70% | 60% | 60% |
| white | 10 dB | **All** | 30 | 0.368 | 0.196 | 90% | 77% | 77% | 87% | 87% |
| white | 5 dB | English | 10 | 0.058 | 0.039 | 100% | 90% | 90% | not run | not run |
| white | 5 dB | Hindi | 10 | 0.577 | 0.267 | 80% | 70% | 70% | not run | not run |
| white | 5 dB | Marathi | 10 | 0.825 | 0.589 | 70% | 80% | 70% | not run | not run |
| white | 5 dB | **All** | 30 | 0.445 | 0.278 | 83% | 80% | 77% | not run | not run |
| babble_fan | 20 dB | English | 10 | 0.000 | 0.000 | 100% | 100% | 100% | not run | not run |
| babble_fan | 20 dB | Hindi | 10 | 0.352 | 0.124 | 100% | 90% | 90% | not run | not run |
| babble_fan | 20 dB | Marathi | 10 | 0.619 | 0.227 | 80% | 80% | 80% | not run | not run |
| babble_fan | 20 dB | **All** | 30 | 0.291 | 0.108 | 93% | 90% | 90% | not run | not run |
| babble_fan | 10 dB | English | 10 | 0.000 | 0.000 | 100% | 100% | 100% | 100% | 100% |
| babble_fan | 10 dB | Hindi | 10 | 0.366 | 0.130 | 100% | 90% | 90% | 100% | 100% |
| babble_fan | 10 dB | Marathi | 10 | 0.762 | 0.429 | 80% | 70% | 70% | 70% | 70% |
| babble_fan | 10 dB | **All** | 30 | 0.336 | 0.173 | 93% | 87% | 87% | 90% | 90% |
| babble_fan | 5 dB | English | 10 | 0.000 | 0.000 | 100% | 100% | 100% | not run | not run |
| babble_fan | 5 dB | Hindi | 10 | 0.577 | 0.359 | 80% | 40% | 40% | not run | not run |
| babble_fan | 5 dB | Marathi | 10 | 0.794 | 0.589 | 90% | 50% | 50% | not run | not run |
| babble_fan | 5 dB | **All** | 30 | 0.414 | 0.291 | 90% | 63% | 63% | not run | not run |
