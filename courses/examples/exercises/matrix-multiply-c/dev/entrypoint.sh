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

exec /usr/sbin/sshd -D -e
