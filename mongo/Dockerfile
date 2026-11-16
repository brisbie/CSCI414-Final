FROM mongo:7.0

# iproute2 is needed so the container can route replies back through our router
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 \
 && rm -rf /var/lib/apt/lists/*

COPY common/net-init.sh /usr/local/bin/net-init.sh
RUN chmod 755 /usr/local/bin/net-init.sh

ENTRYPOINT ["net-init.sh", "docker-entrypoint.sh"]
CMD ["mongod"]
