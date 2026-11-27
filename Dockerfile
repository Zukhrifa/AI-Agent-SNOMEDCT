# Dockerfile — AI Agent SMF Jantung (Streamlit)
# Letakkan file ini di folder project (sejajar app.py), lalu jalankan:
#   docker compose up -d --build
FROM python:3.11-slim

WORKDIR /app

# Dependensi sistem untuk build beberapa paket Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin kode aplikasi + snomed_cardio_umum_full.csv
# (.env, chroma_db/, *.db dikecualikan oleh .dockerignore — lihat docker-compose.yml)
COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]