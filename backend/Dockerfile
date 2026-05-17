FROM python:3.13-slim

# Impede a gravação de arquivos .pyc e não bufferiza o stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências nativas (Tesseract para OCR, dependências do WeasyPrint e Playwright)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-por \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
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
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
