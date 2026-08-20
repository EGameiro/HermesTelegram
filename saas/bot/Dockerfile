FROM python:3.12-slim

WORKDIR /app

# ffmpeg: normaliza o volume dos áudios de lembrete (TTS sai baixo demais).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .

CMD ["python", "-u", "bot.py"]
