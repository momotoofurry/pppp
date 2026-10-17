#!/usr/bin/env bash
# Host-side wrapper (run in WSL2/Linux from anywhere in the repo).
#   docker/run.sh build            # build the image
#   docker/run.sh setup            # clone the upstream repo (code + data) into external/
#   docker/run.sh verify           # quick cross-platform check against committed results (~5 min)
#   docker/run.sh stage1 | stage2 | stage3 | selfcal | all
#   docker/run.sh shell            # interactive shell in the container
# Files are written as the calling user, so results stay editable outside the container.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=${IMAGE:-rf-emg}

if [[ "${1:-}" == build ]]; then
    exec docker build -f docker/Dockerfile -t "$IMAGE" .
fi

case "$PWD" in
    /mnt/?/*) echo "warning: repo is on a Windows drive ($PWD); file access through /mnt is slow." \
                   "Clone it into the WSL filesystem (e.g. ~/model) for real runs." >&2 ;;
esac

TTY=()
[[ -t 0 && -t 1 ]] && TTY=(-it)
CMD=(bash docker/run_all.sh "$@")
[[ "${1:-shell}" == shell ]] && CMD=(bash)

exec docker run --rm "${TTY[@]}" \
    --user "$(id -u):$(id -g)" -e HOME=/tmp \
    --shm-size=2g \
    -v "$PWD":/work -w /work \
    "$IMAGE" "${CMD[@]}"
