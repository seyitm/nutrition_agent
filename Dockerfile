FROM python:3.10-slim

# Depoları güncelle ve temel araçları yükle
RUN apt-get update && apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Chromium için ek depo ekle
RUN echo "deb http://deb.debian.org/debian bookworm main contrib non-free" >> /etc/apt/sources.list
RUN echo "deb http://deb.debian.org/debian-security bookworm-security main contrib non-free" >> /etc/apt/sources.list
RUN apt-get update

# Sistem bağımlılıklarını ve Chromium'u yükle
RUN apt-get install -y \
    wget \
    gnupg \
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    chromium \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "$PORT"]