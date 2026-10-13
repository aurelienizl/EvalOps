FROM debian:bookworm-slim

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    apt-cacher-ng \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN chmod 777 /var/cache/apt-cacher-ng /var/log/apt-cacher-ng

EXPOSE 3142

HEALTHCHECK --interval=5s --timeout=3s --retries=5 \
    CMD curl -f http://127.0.0.1:3142/acng-report.html || exit 1

CMD ["apt-cacher-ng", "-c", "/etc/apt-cacher-ng", "ForeGround=1", "PassThroughPattern=.*"]
