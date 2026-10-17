#!/bin/bash
set -e

ssh-keygen -A


# Ensure student home directory and ssh permissions
mkdir -p /home/student/.ssh
chown -R student:student /home/student
chmod 700 /home/student/.ssh
if [ -f /home/student/.ssh/authorized_keys ]; then
    chmod 600 /home/student/.ssh/authorized_keys
fi

# Ensure exercise workspace directory exists
EX_DIR="${WORKSPACE_DIR:-/home/student/shortest-path-c}"
if [[ "${EX_DIR}" != /* ]]; then
    EX_DIR="/home/student/${EX_DIR}"
fi
mkdir -p "${EX_DIR}"
chown -R student:student "${EX_DIR}"
chmod 775 "${EX_DIR}"

exec /usr/sbin/sshd -D -e
