FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends docker.io ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

RUN mkdir -p /var/lib/awg-bot
ENV DB_PATH=/var/lib/awg-bot/awg-bot.db
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "bot.main"]
