FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend /app/backend
COPY frontend /app/frontend
COPY data /app/data
RUN mkdir -p /app/logs
COPY start.sh /app/start.sh
COPY seed_full_topology.py /app/seed_full_topology.py
RUN chmod +x /app/start.sh
EXPOSE 10000
CMD ["/app/start.sh"]

COPY jobs /app/jobs
COPY Cargadores.py /app/Cargadores.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh
