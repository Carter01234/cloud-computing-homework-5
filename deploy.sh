#!/bin/bash
# Creates the file-server VM and the error-logger VM in parallel, then waits
# until both have finished their startup scripts and are running their software.
#
# Usage (from the homework4/ folder):
#   ./deploy.sh            create both VMs (fails if either already exists)
#   ./deploy.sh --replace  delete any existing VMs with these names first

set -euo pipefail

# ---------- Configuration ----------
PROJECT_ID="project-8aeecca0-4f70-4c6b-8e3"
ZONE="us-central1-a"
SERVICE_ACCOUNT="web-server-sa@${PROJECT_ID}.iam.gserviceaccount.com"

SERVER_VM="my-vm"
SERVER_MACHINE_TYPE="e2-micro"
SERVER_IP_NAME="homework4-ip"         # reserved static external IP
SERVER_PORT=8080

LOGGER_VM="error-logger-vm"
LOGGER_MACHINE_TYPE="e2-micro"

STARTUP_TIMEOUT_SECONDS=900           # first boot installs packages; allow 15 min
# -----------------------------------

# Always run relative to this script's folder, so the file paths below resolve
cd "$(dirname "$0")"

for f in file-server/startup.sh file-server/file-server.py error-logger/error-logger-startup.sh error-logger/error-logger.py; do
  [[ -f "$f" ]] || { echo "ERROR: missing $f (run this from homework4/)"; exit 1; }
done

gcloud config set project "$PROJECT_ID" --quiet >/dev/null 2>&1

vm_exists() {
  gcloud compute instances describe "$1" --zone="$ZONE" --format="value(name)" >/dev/null 2>&1
}

# ---------- Handle existing VMs ----------
for vm in "$SERVER_VM" "$LOGGER_VM"; do
  if vm_exists "$vm"; then
    if [[ "${1:-}" == "--replace" ]]; then
      echo "Deleting existing VM $vm..."
      gcloud compute instances delete "$vm" --zone="$ZONE" --quiet &
    else
      echo "ERROR: VM $vm already exists. Rerun with --replace to delete and recreate it."
      exit 1
    fi
  fi
done
wait   # for any deletions to finish

# ---------- Create both VMs in parallel ----------
echo "Creating $SERVER_VM and $LOGGER_VM..."

gcloud compute instances create "$SERVER_VM" \
  --zone="$ZONE" \
  --machine-type="$SERVER_MACHINE_TYPE" \
  --address="$SERVER_IP_NAME" \
  --service-account="$SERVICE_ACCOUNT" \
  --scopes=cloud-platform \
  --metadata-from-file=startup-script=file-server/startup.sh,file-server-py=file-server/file-server.py \
  > /tmp/deploy-server.log 2>&1 &
SERVER_PID=$!

gcloud compute instances create "$LOGGER_VM" \
  --zone="$ZONE" \
  --machine-type="$LOGGER_MACHINE_TYPE" \
  --service-account="$SERVICE_ACCOUNT" \
  --scopes=cloud-platform \
  --metadata-from-file=startup-script=error-logger/error-logger-startup.sh,error-logger-py=error-logger/error-logger.py \
  > /tmp/deploy-logger.log 2>&1 &
LOGGER_PID=$!

failed=0
wait "$SERVER_PID" || { echo "ERROR creating $SERVER_VM:"; cat /tmp/deploy-server.log; failed=1; }
wait "$LOGGER_PID" || { echo "ERROR creating $LOGGER_VM:"; cat /tmp/deploy-logger.log; failed=1; }
[[ $failed -eq 0 ]] || exit 1
echo "Both VMs created. Waiting for their startup scripts to finish (first boot can take several minutes)..."

# ---------- Wait for both startup scripts to finish ----------
# Reads each VM's serial console, which works even before SSH is available.
wait_for_startup() {
  local vm=$1 waited=0
  while (( waited < STARTUP_TIMEOUT_SECONDS )); do
    if gcloud compute instances get-serial-port-output "$vm" --zone="$ZONE" 2>/dev/null \
        | grep -q "Finished running startup scripts"; then
      echo "  $vm: startup script finished after ~${waited}s"
      return 0
    fi
    sleep 15
    waited=$((waited + 15))
  done
  echo "  $vm: startup script did not finish within ${STARTUP_TIMEOUT_SECONDS}s"
  return 1
}

wait_for_startup "$SERVER_VM" & SERVER_WAIT_PID=$!
wait_for_startup "$LOGGER_VM" & LOGGER_WAIT_PID=$!
server_ok=0; logger_ok=0
wait "$SERVER_WAIT_PID" && server_ok=1
wait "$LOGGER_WAIT_PID" && logger_ok=1

# ---------- Check that the server answers HTTP ----------
SERVER_IP=$(gcloud compute instances describe "$SERVER_VM" --zone="$ZONE" \
  --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

http_ok=0
if (( server_ok )); then
  for _ in {1..12}; do
    # Any HTTP status (even 404) means the server process is up and answering
    if curl -s -o /dev/null --max-time 5 "http://${SERVER_IP}:${SERVER_PORT}/"; then
      http_ok=1; break
    fi
    sleep 5
  done
fi

# ---------- Summary ----------
echo
echo "========== Deployment summary =========="
if (( http_ok )); then
  echo "File server:  RUNNING at http://${SERVER_IP}:${SERVER_PORT}"
else
  echo "File server:  NOT RESPONDING at http://${SERVER_IP}:${SERVER_PORT}"
  echo "  Debug: gcloud compute ssh $SERVER_VM --zone=$ZONE --command='sudo tail -30 /var/log/file-server.log'"
fi
if (( logger_ok )); then
  echo "Error logger: startup finished on $LOGGER_VM"
  echo "  Watch it:  gcloud compute ssh $LOGGER_VM --zone=$ZONE --command='sudo tail -f /var/log/error-logger.log'"
else
  echo "Error logger: startup did NOT finish on $LOGGER_VM"
  echo "  Debug: gcloud compute ssh $LOGGER_VM --zone=$ZONE --command='sudo journalctl -u google-startup-scripts.service --no-pager | tail -40'"
fi
echo "========================================"

(( http_ok && logger_ok ))