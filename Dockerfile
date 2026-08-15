# ADS-B Guard — Streamlit dashboard konteyneri
FROM python:3.12-slim

WORKDIR /app

# Bagimliliklar (once requirements, katman onbellegi icin)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama
COPY . .

# Streamlit portu
EXPOSE 8501

# Kota/alarm dosyalari icin (opsiyonel) volume: -v adsb_data:/app
# Kimlik/AI icin ortam degiskenleri: OPENSKY_USER, OPENSKY_PASS, ANTHROPIC_API_KEY

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
