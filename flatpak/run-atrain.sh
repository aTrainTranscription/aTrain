#!/bin/bash
set -eo pipefail

# Workaround for WebKitGTK sandbox graphics driver/GBM issues (especially on NVIDIA) https://github.com/aTrainTranscription/aTrain/issues/151#issuecomment-4901338674
export WEBKIT_DISABLE_DMABUF_RENDERER=1
# Force pywebview to use GTK directly and avoid loading warnings for QT
export PYWEBVIEW_GUI=gtk

required_models_present() {
    if [[ -n "${REQUIRED_MODEL_1:-}" && -n "${REQUIRED_MODEL_2:-}" ]]; then
        [[ -d "${REQUIRED_MODEL_1}" && -d "${REQUIRED_MODEL_2}" ]]
        return
    fi

    python3 - <<'PY'
from aTrain_core.globals import REQUIRED_MODELS, REQUIRED_MODELS_DIR

missing = [name for name in REQUIRED_MODELS if not (REQUIRED_MODELS_DIR / name).is_dir()]
raise SystemExit(1 if missing else 0)
PY
}

transcription_dir=""

while (($#)); do
    [[ "$1" == "--transcription-dir" ]] || break
    [[ $# -ge 2 ]] || {
        echo "Missing path after --transcription-dir" >&2
        exit 2
    }
    transcription_dir="$2"
    shift 2
done

if [[ -n "$transcription_dir" ]]; then
    mkdir -p "$transcription_dir"/{transcriptions,settings,models}
    export ATRAIN_USER_DIR="$transcription_dir"
fi

for dir in \
    /app/lib/python*/site-packages/nvidia/*/lib \
    /usr/lib/*/GL/default/lib \
    /usr/lib/extensions/nvidia/lib \
    /usr/lib/extensions/nvidia-*/lib
do
    [[ -d "$dir" ]] || continue
    case ":${LD_LIBRARY_PATH-}:" in
        *":${dir}:"*) ;;
        *)
            LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+${LD_LIBRARY_PATH}:}${dir}"
            ;;
    esac
done
export LD_LIBRARY_PATH

if ! required_models_present; then
    echo "Models not found. Running aTrain init..."
    aTrain init
fi

exec aTrain start "$@"
