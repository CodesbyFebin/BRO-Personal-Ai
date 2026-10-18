FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BRO_HOST=0.0.0.0 BRO_PORT=8787 BRO_DB_PATH=/app/data/bro.db
WORKDIR /app
COPY server.py main.py ./
COPY core ./core
COPY web ./web
COPY domains ./domains
COPY integrations ./integrations
COPY voice ./voice
RUN useradd --create-home --uid 10001 bro && mkdir -p /app/data && chown -R bro:bro /app
USER bro
EXPOSE 8787
HEALTHCHECK --interval=20s --timeout=3s --start-period=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=2)" || exit 1
CMD ["python", "main.py"]
