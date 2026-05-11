#!/usr/bin/env bash
set -u
set -o pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <command> [args...]"
  exit 2
fi

max_restarts="${MAX_RESTARTS:-100}"
restart_delay_seconds="${RESTART_DELAY_SECONDS:-30}"
log_dir="${RESUMABLE_LOG_DIR:-swebench_task/artifacts/logs}"
mkdir -p "$log_dir"

run_name="${RESUMABLE_RUN_NAME:-$(date +%Y%m%d_%H%M%S)}"
wrapper_log="$log_dir/${run_name}.resumable.log"
attempt=1

echo "Resumable command started at $(date)" | tee -a "$wrapper_log"
echo "Command: $*" | tee -a "$wrapper_log"
echo "Max restarts: $max_restarts; delay: ${restart_delay_seconds}s" | tee -a "$wrapper_log"

while true; do
  echo "" | tee -a "$wrapper_log"
  echo "[$(date)] attempt $attempt starting" | tee -a "$wrapper_log"

  "$@" 2>&1 | tee -a "$wrapper_log"
  exit_code="${PIPESTATUS[0]}"

  if [ "$exit_code" -eq 0 ]; then
    echo "[$(date)] command completed successfully" | tee -a "$wrapper_log"
    exit 0
  fi

  if [ "$attempt" -gt "$max_restarts" ]; then
    echo "[$(date)] command failed with exit code $exit_code after $attempt attempts" | tee -a "$wrapper_log"
    exit "$exit_code"
  fi

  echo "[$(date)] command failed with exit code $exit_code; restarting in ${restart_delay_seconds}s" | tee -a "$wrapper_log"
  sleep "$restart_delay_seconds"
  attempt=$((attempt + 1))
done
