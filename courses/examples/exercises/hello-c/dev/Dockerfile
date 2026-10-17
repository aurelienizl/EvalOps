FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    ca-certificates \
    coreutils \
    curl \
    gdb \
    nano \
    openssh-server \
    procps \
    vim \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/ssh/ssh_host_*

RUN groupadd -g 1000 student \
    && useradd -u 1000 -g 1000 -m -s /bin/bash student \
    && passwd -d student \
    && install -d -m 755 /etc/training/authorized_keys

COPY entrypoint.sh /entrypoint.sh

WORKDIR /home/student
EXPOSE 22
HEALTHCHECK --interval=2s --timeout=3s --retries=30 CMD test -s /run/sshd.pid
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
