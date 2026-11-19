FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 --create-home app

COPY --chown=app:app *.py ./screener/
COPY --chown=app:app application/ ./screener/application/
COPY --chown=app:app domain/ ./screener/domain/
COPY --chown=app:app market_data/ ./screener/market_data/
COPY --chown=app:app infrastructure/ ./screener/infrastructure/

USER 10001:10001
ENTRYPOINT ["python3", "-m", "screener.run_daily"]