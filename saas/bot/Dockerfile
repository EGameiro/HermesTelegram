FROM python:3.12-slim

WORKDIR /app

# ffmpeg: normaliza o volume dos áudios de lembrete (TTS sai baixo demais).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o pacote (módulos de topo + subpacote channels/). O .dockerignore
# exclui .venv/__pycache__. Rollback = redeploy do commit anterior (Dokploy/git).
COPY . .

# Porta do webhook do WhatsApp (FastAPI/uvicorn) quando o canal WhatsApp está ativo.
# Só é usada se UAZAPI_BASE_URL+UAZAPI_TOKEN estiverem no Environment; o Telegram
# (long polling) não precisa de porta. Ajuste com PORT.
EXPOSE 8080

CMD ["python", "-u", "app.py"]
