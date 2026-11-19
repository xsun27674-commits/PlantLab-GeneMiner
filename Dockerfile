# syntax=docker/dockerfile:1
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
ENV BROWSER_PATH=/usr/bin/chromium

WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=pip_ca \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY src/ src/
COPY data/ data/
COPY .streamlit/config.toml .streamlit/config.toml
EXPOSE 7860
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=7860", "--server.headless=true"]
