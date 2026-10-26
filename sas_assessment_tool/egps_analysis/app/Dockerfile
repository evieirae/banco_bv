# Imagem única do app na AWS (ADR 0005): front buildado + backend FastAPI + sincronização.
# App: CMD padrão. Sincronização: command ["python", "-m", "sync.sincroniza"] na task definition.
FROM node:20-slim AS front
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite.config.ts: outDir "../static" -> /app/static
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY db/ db/
COPY sync/ sync/
COPY paridade/ paridade/
COPY --from=front /app/static static/
ENV PYTHONUNBUFFERED=1 APP_PORT=8000
EXPOSE 8000
USER nobody
CMD ["python", "backend/main.py"]
