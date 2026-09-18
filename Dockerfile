FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BRICKLENS_AUTOSTART=0
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .
COPY config ./config
COPY models ./models
COPY vendor ./vendor
COPY web ./web
EXPOSE 8000
CMD ["bricklens", "serve", "--config", "config/bricklens.yaml"]
