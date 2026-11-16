FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      iproute2 iputils-ping curl netcat-openbsd \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir httpx==0.28.1 pymongo==4.13.2 matplotlib==3.10.3

COPY common/net-init.sh /usr/local/bin/net-init.sh
COPY ops/monitor.py ops/import_data.py ops/analyze.py /app/
RUN chmod 755 /usr/local/bin/net-init.sh

WORKDIR /app
ENTRYPOINT ["net-init.sh"]
CMD ["python", "-u", "/app/monitor.py"]
