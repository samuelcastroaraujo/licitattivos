FROM python:3.12-slim

# Impede a gravação de arquivos .pyc e não bufferiza o stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências nativas (Tesseract para OCR, WeasyPrint, Playwright).
# LibreOffice converte proposta e declarações para PDF (no Windows quem converte é o Word);
# fonts-liberation tem as mesmas medidas da Arial do modelo, então o layout não muda.
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-por \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    libreoffice-writer-nogui \
    fonts-liberation \
    fonts-dejavu-core \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Instalação do uv (Gerenciador de pacotes rápido)
RUN pip install uv

# Copia arquivos de configuração do uv e instala dependências Python
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv pip install --system -r pyproject.toml

# Instala os browsers do Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# Copia o código da aplicação
COPY backend/ .

# Comando de inicialização
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
