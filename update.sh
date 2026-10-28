# Run this in a-Shell on your iPhone to download the latest code from GitHub:
#   sh update.sh
REPO="https://raw.githubusercontent.com/ssenapathy24/sleepsense/main"
for f in sleep_calc.py sleepsense_core.py sleepsense_metrics.py config.json sample_log.txt sample_steps.txt; do
  curl -sL -o "$f" "$REPO/$f" && echo "updated $f"
done
