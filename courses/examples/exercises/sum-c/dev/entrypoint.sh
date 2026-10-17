#!/bin/sh
set -eu

mkdir -p /run/sshd
if [ ! -f /etc/training/host_key ]; then
    ssh-keygen -A
fi
su -s /bin/sh -c 'cp -Rn /etc/skel/. /home/student/' student
exec /usr/sbin/sshd -D -e
