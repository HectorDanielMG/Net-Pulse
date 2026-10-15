FROM python:3.10-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install --no-install-recommends -y iproute2 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY netpulse ./netpulse
COPY web ./web
ENV DATABASE_PATH=/data/netpulse.db
EXPOSE 8000
CMD ["uvicorn", "netpulse.main:app", "--host", "0.0.0.0", "--port", "8000"]
