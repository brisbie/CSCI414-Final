FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      iproute2 iputils-ping iperf3 netcat-openbsd curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/net-init.sh /usr/local/bin/net-init.sh
COPY api/app.py api/start.sh ./
RUN chmod 755 /usr/local/bin/net-init.sh start.sh

EXPOSE 8443 5201
ENTRYPOINT ["net-init.sh"]
CMD ["./start.sh"]
