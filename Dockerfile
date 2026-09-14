FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 flycoder \
    && mkdir -p /data/runs && chown -R flycoder:flycoder /data
WORKDIR /app
COPY --chown=flycoder:flycoder flycoder /app/flycoder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLYCODER_RUNS=/data/runs
USER flycoder
ENTRYPOINT ["python", "-m", "flycoder"]
CMD ["demo"]
