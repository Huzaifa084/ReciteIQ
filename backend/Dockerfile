FROM python:3.12-slim

WORKDIR /app

# Layer-cache deps: install from pyproject before copying source
COPY pyproject.toml ./
RUN pip install --no-cache-dir tomli && python - <<'EOF' > /tmp/reqs.txt
import tomli
d = tomli.load(open("pyproject.toml", "rb"))
print("\n".join(d["project"]["dependencies"] + d["project"]["optional-dependencies"]["asr"]))
EOF
RUN pip install --no-cache-dir -r /tmp/reqs.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

# Whisper CT2 + silero ONNX models are volume-mounted at /app/models (kept out
# of the image so model swaps don't rebuild). Threads pinned for the 6-core box.
ENV OMP_NUM_THREADS=2 \
    RECITEIQ_ASR_MODEL_PATH=models/whisper-base-ar-quran-ct2

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info"]
