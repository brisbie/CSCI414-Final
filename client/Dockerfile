FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      iproute2 iputils-ping traceroute iperf3 netcat-openbsd curl tcpdump ca-certificates procps \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir httpx==0.28.1

COPY common/net-init.sh /usr/local/bin/net-init.sh
COPY client/loadgen.py /app/loadgen.py
RUN chmod 755 /usr/local/bin/net-init.sh /app/loadgen.py

WORKDIR /app
ENTRYPOINT ["net-init.sh"]
CMD ["sleep", "infinity"]
