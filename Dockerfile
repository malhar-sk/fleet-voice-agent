# Voice app: FastAPI + Pipecat (SmallWebRTC) + faster-whisper + Piper. CPU only.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 STT_THREADS=1 HF_HUB_DISABLE_TELEMETRY=1
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY agent agent
COPY voice voice
COPY web web
COPY scripts/download_models.py scripts/download_models.py
EXPOSE 7860
# models live in a mounted folder; the first start downloads them (~780 MB) if missing
CMD ["sh", "-c", "python scripts/download_models.py && python -m voice.server"]
