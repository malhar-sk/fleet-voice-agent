"""Download the speech models into ./models (about 780 MB). Safe to re-run: skips files already there.

  python scripts/download_models.py
faster-whisper `small` (Systran/faster-whisper-small, MIT) and five Piper voices from
rhasspy/piper-voices (each voice's MODEL_CARD has its licence: lessac/amy/rohan/pratham/google-mr).
"""
import os
import sys
import urllib.request

ROOT = os.environ.get("MODELS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"))
PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES = ["en/en_US/lessac/medium/en_US-lessac-medium", "en/en_US/amy/medium/en_US-amy-medium",
          "hi/hi_IN/pratham/medium/hi_IN-pratham-medium", "hi/hi_IN/rohan/medium/hi_IN-rohan-medium",
          "mr/mr_IN/google/medium/mr_IN-google-medium"]
WHISPER = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/"
WHISPER_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
# --extra (eval round 2, `make eval-stt` only; the app does not use them): both MIT licensed
EXTRA = {
    "whisper-medium": ("https://huggingface.co/Systran/faster-whisper-medium/resolve/main/",
                       ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]),
    "whisper-large-v3-turbo": ("https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2/resolve/main/",
                               ["config.json", "preprocessor_config.json", "tokenizer.json", "vocabulary.json", "model.bin"]),
}


def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print("downloading", url, flush=True)
    tmp = dest + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, dest)


def main():
    for v in VOICES:
        name = v.rsplit("/", 1)[-1]
        fetch(PIPER + v + ".onnx", os.path.join(ROOT, "piper", name + ".onnx"))
        fetch(PIPER + v + ".onnx.json", os.path.join(ROOT, "piper", name + ".onnx.json"))
    for f in WHISPER_FILES:
        fetch(WHISPER + f, os.path.join(ROOT, "whisper-small", f))
    if "--extra" in sys.argv:
        for name, (base, files) in EXTRA.items():
            for f in files:
                fetch(base + f, os.path.join(ROOT, name, f))
    print("models ready in", ROOT)


if __name__ == "__main__":
    sys.exit(main())
