FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    requests \
    psutil \
    kubernetes \
    grpcio \
    grpcio-tools \
    cryptography

COPY . .

CMD ["python", "normal_agent.py"]
