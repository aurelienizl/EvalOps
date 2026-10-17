FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    gcc \
    build-essential \
    make \
    bash \
    coreutils \
    curl \
    nano \
    vim \
    netcat-openbsd \
    ca-certificates \
    procps \
    sudo \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 student && \
    useradd -u 1000 -g 1000 -m -s /bin/bash student && \
    passwd -d student

RUN mkdir -p /var/run/sshd /etc/training/authorized_keys && \
    chmod 755 /etc/training/authorized_keys

RUN echo "Port 22" > /etc/ssh/sshd_config.d/devops.conf && \
    echo "PermitRootLogin no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "AuthorizedKeysFile .ssh/authorized_keys /etc/training/authorized_keys/%u" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "StrictModes no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "KbdInteractiveAuthentication no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "UsePAM yes" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "UseDNS no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "ClientAliveInterval 30" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "ClientAliveCountMax 5" >> /etc/ssh/sshd_config.d/devops.conf

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22

WORKDIR /home/student

HEALTHCHECK --interval=2s --timeout=3s --retries=30 CMD nc -z 127.0.0.1 22 || exit 1

ENTRYPOINT ["/entrypoint.sh"]

