#!/bin/bash -x
# need sudo priority

cd /lib/systemd/system
cat << EOF > web-badge-flask.service
[Unit]
Description=Badge server startup

[Service]
User=zuul
Group=zuul
Type=forking
ExecStart=/home/zuul/setup-openlab-badge.sh

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
