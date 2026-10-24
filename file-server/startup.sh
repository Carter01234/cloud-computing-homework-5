#!/bin/bash
# GCE startup script: runs as root every time the VM boots.
 
APP_DIR=/opt/file-server
VENV_DIR=$APP_DIR/venv
 
mkdir -p "$APP_DIR"
 
# One-time setup: create a virtual environment with google-cloud-storage.
# Skipped on later boots because the venv already exists.
# -x means "is there an executable at this location?"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  apt-get update
  apt-get install -y python3-venv
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install google-cloud-storage google-cloud-logging google-cloud-pubsub
fi
 
# Pull file-server.py out of the instance metadata and save it on the VM
curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/file-server-py" \
  -o "$APP_DIR/file-server.py"
 
# Start the server with the venv's Python so it can import google.cloud.storage
nohup "$VENV_DIR/bin/python" "$APP_DIR/file-server.py" > /var/log/file-server.log 2>&1 &