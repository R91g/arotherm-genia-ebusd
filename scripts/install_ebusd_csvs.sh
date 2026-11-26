#!/usr/bin/env sh
# ==============================================================================
# aroTHERM & GeniaAir (eBUS) — eBUSd CSV Installer & Updater
# ==============================================================================
# Installs (first-time setup) or updates the bundled eBUSd CSV configuration
# files from https://github.com/R91g/arotherm-genia-ebusd without touching any
# unrelated user CSVs.
#
# Quick usage (latest stable release, auto-detect destination):
#   curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/scripts/install_ebusd_csvs.sh | sh
#
# Options (pass via `sh -s -- <options>` when piping from curl):
#   -d, --dir <PATH>        Target eBUSd config root (where broadcast.csv and vaillant/ live)
#   -v, --version <TAG>     Download from a specific tag/ref (e.g. v1.3.2)
#       --ref <REF>         Alias for --version
#       --main              Download from the 'main' branch (unreleased fixes)
#       --no-backup         Do not back up modified files before overwriting
#       --dry-run           Download & validate only; do not modify target files
#       --reload            Send 'reload' to eBUSd over TCP after changes
#       --ebusd-host <HOST> eBUSd TCP host for --reload (default: auto-detect)
#       --ebusd-port <PORT> eBUSd TCP port for --reload (default: 8888)
#   -h, --help              Show this help message
# ==============================================================================

set -eu

REPO="R91g/arotherm-genia-ebusd"
RAW_BASE="https://raw.githubusercontent.com/${REPO}"
API_LATEST="https://api.github.com/repos/${REPO}/releases/latest"

# Exact list of CSV files shipped in ebusd-configuration/
CSV_FILES="
broadcast.csv
vaillant/04.netx3.csv
vaillant/08.hmu.csv
vaillant/08.hmu.HW5103.csv
vaillant/08.hmux0.csv
vaillant/15.bass3.csv
vaillant/15.basv3.csv
vaillant/15.ctlv2.csv
vaillant/15.ctlv3.csv
vaillant/52.vr_70.csv
vaillant/76.vwzio.csv
vaillant/f6.netx3.csv
"

TARGET_DIR=""
GIT_REF=""
USE_MAIN=0
DO_BACKUP=1
DRY_RUN=0
DO_RELOAD=0
EBUSD_HOST=""
EBUSD_PORT=8888
DETECTED_ENV="custom"
DETECTED_ADDON_SLUG=""

print_help() {
    cat <<'EOF'
aroTHERM & GeniaAir (eBUS) — eBUSd CSV Installer & Updater

Usage:
  install_ebusd_csvs.sh [OPTIONS]
  curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/scripts/install_ebusd_csvs.sh | sh -s -- [OPTIONS]

Options:
  -d, --dir <PATH>        Target eBUSd config directory (contains broadcast.csv & vaillant/)
  -v, --version <TAG>     Install CSVs from a specific release tag (e.g. v1.3.2)
      --ref <REF>         Install CSVs from a specific branch, tag, or commit SHA
      --main              Install latest CSVs from the 'main' branch
      --no-backup         Skip creating a timestamped backup of modified files
      --dry-run           Download and compare without writing to the target directory
      --reload            Trigger eBUSd TCP 'reload' after installing/updating files
      --ebusd-host <HOST> eBUSd TCP host for --reload (default: b4d7ad18-ebusd or 127.0.0.1)
      --ebusd-port <PORT> eBUSd TCP port for --reload (default: 8888)
  -h, --help              Show this help and exit

Examples:
  # Install or update using the latest stable release (auto-detects HAOS add-on or /etc/ebusd):
  curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/scripts/install_ebusd_csvs.sh | sh

  # Install into a custom Docker volume directory:
  curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/scripts/install_ebusd_csvs.sh | sh -s -- -d /srv/ebusd/en

  # Pull unreleased CSV fixes from main (dry run first):
  curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/main/scripts/install_ebusd_csvs.sh | sh -s -- --main --dry-run
EOF
}

log() {
    printf '%s\n' "$*"
}

err() {
    printf 'ERROR: %s\n' "$*" >&2
}

# Parse CLI arguments
while [ $# -gt 0 ]; do
    case "$1" in
        -d|--dir)
            [ $# -ge 2 ] || { err "Missing argument for $1"; exit 1; }
            TARGET_DIR="$2"
            shift 2
            ;;
        -v|--version|--ref)
            [ $# -ge 2 ] || { err "Missing argument for $1"; exit 1; }
            GIT_REF="$2"
            shift 2
            ;;
        --main)
            USE_MAIN=1
            shift
            ;;
        --no-backup)
            DO_BACKUP=0
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --reload)
            DO_RELOAD=1
            shift
            ;;
        --ebusd-host)
            [ $# -ge 2 ] || { err "Missing argument for $1"; exit 1; }
            EBUSD_HOST="$2"
            shift 2
            ;;
        --ebusd-port)
            [ $# -ge 2 ] || { err "Missing argument for $1"; exit 1; }
            EBUSD_PORT="$2"
            shift 2
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            err "Unknown option: $1 (use --help for usage)"
            exit 1
            ;;
    esac
done

# Pick HTTP client (curl preferred, wget fallback)
if command -v curl >/dev/null 2>&1; then
    HTTP_TOOL="curl"
elif command -v wget >/dev/null 2>&1; then
    HTTP_TOOL="wget"
else
    err "Neither 'curl' nor 'wget' was found. Please install one and retry."
    exit 1
fi

http_get_stdout() {
    if [ "$HTTP_TOOL" = "curl" ]; then
        curl -fsSL "$1"
    else
        wget -qO- "$1"
    fi
}

http_download() {
    url="$1"
    dest="$2"
    if [ "$HTTP_TOOL" = "curl" ]; then
        curl -fsSL "$url" -o "$dest"
    else
        wget -qO "$dest" "$url"
    fi
}

# Resolve target directory
detect_target_dir() {
    if [ -n "$TARGET_DIR" ]; then
        DETECTED_ENV="custom"
        return 0
    fi

    # 1. Home Assistant eBUSd Add-on (standard LukasGrebe slug first, then any *_ebusd)
    if [ -d "/addon_configs/b4d7ad18_ebusd" ]; then
        DETECTED_ENV="ha_addon"
        DETECTED_ADDON_SLUG="b4d7ad18_ebusd"
        TARGET_DIR="/addon_configs/b4d7ad18_ebusd/ebusd-configuration/en"
        return 0
    fi

    for addon_dir in /addon_configs/*_ebusd; do
        if [ -d "$addon_dir" ]; then
            DETECTED_ENV="ha_addon"
            DETECTED_ADDON_SLUG=$(basename "$addon_dir")
            TARGET_DIR="${addon_dir}/ebusd-configuration/en"
            return 0
        fi
    done

    # 2. Home Assistant shared folder (/share/ebusd-configuration — accessible from both HA Core shell_command and eBUSd add-on)
    if [ -d "/share/ebusd-configuration" ]; then
        DETECTED_ENV="ha_share"
        DETECTED_ADDON_SLUG="b4d7ad18_ebusd"
        TARGET_DIR="/share/ebusd-configuration/en"
        return 0
    fi

    # 3. Standalone Linux / Docker host (/etc/ebusd)
    if [ -d "/etc/ebusd" ]; then
        DETECTED_ENV="linux"
        TARGET_DIR="/etc/ebusd/en"
        return 0
    fi

    err "Could not auto-detect an eBUSd configuration directory."
    err "Checked: /addon_configs/*_ebusd, /share/ebusd-configuration, and /etc/ebusd."
    err "Please specify your directory explicitly with: -d /path/to/ebusd-configuration/en"
    exit 1
}

# Resolve git ref (latest stable release by default)
resolve_git_ref() {
    if [ -n "$GIT_REF" ]; then
        return 0
    fi
    if [ "$USE_MAIN" -eq 1 ]; then
        GIT_REF="main"
        return 0
    fi

    latest_tag=""
    if api_json=$(http_get_stdout "$API_LATEST" 2>/dev/null); then
        latest_tag=$(printf '%s\n' "$api_json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
    fi

    if [ -n "$latest_tag" ]; then
        GIT_REF="$latest_tag"
    else
        log "Warning: could not query GitHub latest release API; falling back to 'main'."
        GIT_REF="main"
    fi
}

# Basic sanity validation so an HTML error page never overwrites a real CSV
validate_csv() {
    file_path="$1"
    if [ ! -s "$file_path" ]; then
        return 1
    fi
    first_line=$(head -n 1 "$file_path")
    case "$first_line" in
        *'<html'*|*'<HTML'*|*'<!DOCTYPE'*|*'<!doctype'*)
            return 1
            ;;
    esac
    if grep -q '^type,circuit,' "$file_path"; then
        return 0
    fi
    return 1
}

detect_target_dir
resolve_git_ref

IS_FRESH_INSTALL=0
if [ ! -f "${TARGET_DIR}/broadcast.csv" ] && [ ! -d "${TARGET_DIR}/vaillant" ]; then
    IS_FRESH_INSTALL=1
fi

log "========================================================================"
log " aroTHERM & GeniaAir (eBUS) — eBUSd CSV Installer / Updater"
log "========================================================================"
log " Source ref : ${REPO} @ ${GIT_REF}"
log " Target dir : ${TARGET_DIR}"
if [ "$IS_FRESH_INSTALL" -eq 1 ]; then
    log " Mode       : Fresh installation"
else
    log " Mode       : Update existing configuration"
fi
if [ "$DRY_RUN" -eq 1 ]; then
    log " Dry run    : YES (no files will be modified)"
fi
log ""

# Stage all downloads into a temporary directory first (atomic)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

log "Downloading and validating CSV files..."
mkdir -p "${TMP_DIR}/vaillant"
for rel in $CSV_FILES; do
    url="${RAW_BASE}/${GIT_REF}/ebusd-configuration/${rel}"
    staged="${TMP_DIR}/${rel}"
    if ! http_download "$url" "$staged"; then
        err "Failed to download ${url}"
        err "Aborted without modifying any files in ${TARGET_DIR}."
        exit 1
    fi
    if ! validate_csv "$staged"; then
        err "Downloaded file '${rel}' failed CSV validation."
        err "Aborted without modifying any files in ${TARGET_DIR}."
        exit 1
    fi
done
log "All CSV files downloaded and verified."
log ""

INSTALLED=0
UPDATED=0
UNCHANGED=0
BACKUP_DIR=""
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "${TARGET_DIR}/vaillant"
fi

for rel in $CSV_FILES; do
    staged="${TMP_DIR}/${rel}"
    dest="${TARGET_DIR}/${rel}"

    if [ -f "$dest" ]; then
        if cmp -s "$staged" "$dest"; then
            UNCHANGED=$((UNCHANGED + 1))
            log "  [unchanged] ${rel}"
        else
            UPDATED=$((UPDATED + 1))
            if [ "$DRY_RUN" -eq 1 ]; then
                log "  [would update] ${rel}"
            else
                if [ "$DO_BACKUP" -eq 1 ]; then
                    if [ -z "$BACKUP_DIR" ]; then
                        BACKUP_DIR="${TARGET_DIR}/.backup_${TIMESTAMP}"
                    fi
                    mkdir -p "$(dirname "${BACKUP_DIR}/${rel}")"
                    cp -p "$dest" "${BACKUP_DIR}/${rel}"
                fi
                cp "$staged" "$dest"
                log "  [updated]   ${rel}"
            fi
        fi
    else
        INSTALLED=$((INSTALLED + 1))
        if [ "$DRY_RUN" -eq 1 ]; then
            log "  [would install] ${rel}"
        else
            cp "$staged" "$dest"
            log "  [installed] ${rel}"
        fi
    fi
done

log ""
log "Summary: ${INSTALLED} installed, ${UPDATED} updated, ${UNCHANGED} unchanged."
if [ -n "$BACKUP_DIR" ]; then
    log "Backup : ${BACKUP_DIR}"
fi

# Optional live TCP reload
RELOAD_OK=0
if [ "$DO_RELOAD" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
    if [ $((INSTALLED + UPDATED)) -eq 0 ]; then
        log "No CSV changes detected; skipping eBUSd reload."
    else
        reload_host="$EBUSD_HOST"
        if [ -z "$reload_host" ]; then
            if [ "$DETECTED_ENV" = "ha_addon" ] || [ "$DETECTED_ENV" = "ha_share" ]; then
                if [ -n "$DETECTED_ADDON_SLUG" ]; then
                    reload_host=$(printf '%s' "$DETECTED_ADDON_SLUG" | tr '_' '-')
                else
                    reload_host="b4d7ad18-ebusd"
                fi
            else
                case "$TARGET_DIR" in
                    /share/*) reload_host="b4d7ad18-ebusd" ;;
                    *) reload_host="127.0.0.1" ;;
                esac
            fi
        fi
        log ""
        log "Sending 'reload' to eBUSd (${reload_host}:${EBUSD_PORT})..."
        reload_out=""
        if command -v ebusctl >/dev/null 2>&1; then
            if reload_out=$(ebusctl -s "$reload_host" -p "$EBUSD_PORT" reload 2>&1); then
                log "$reload_out"
                case "$reload_out" in
                    *done*) RELOAD_OK=1 ;;
                esac
            else
                [ -n "$reload_out" ] && log "$reload_out"
                log "Warning: ebusctl reload failed; please restart eBUSd manually."
            fi
        elif command -v nc >/dev/null 2>&1; then
            if reload_out=$(printf 'reload\n' | nc -w 5 "$reload_host" "$EBUSD_PORT" 2>&1); then
                log "$reload_out"
                case "$reload_out" in
                    *done*) RELOAD_OK=1 ;;
                esac
            else
                [ -n "$reload_out" ] && log "$reload_out"
                log "Warning: TCP reload failed; please restart eBUSd manually."
            fi
        else
            log "Warning: neither 'ebusctl' nor 'nc' is available; please restart eBUSd manually."
        fi
    fi
fi

# Helpful next steps
if [ "$DRY_RUN" -eq 0 ] && [ $((INSTALLED + UPDATED)) -gt 0 ]; then
    log ""
    if [ "$RELOAD_OK" -eq 1 ] && [ "$IS_FRESH_INSTALL" -eq 0 ]; then
        log "eBUSd reloaded the updated CSVs live (no add-on/service restart needed)."
    else
        log "Next steps:"
        if [ "$DETECTED_ENV" = "ha_addon" ]; then
            if [ "$IS_FRESH_INSTALL" -eq 1 ]; then
                log "  1. Open Settings -> Apps/Add-ons -> eBUSd -> Configuration."
                log "  2. Disable 'Seed HA MQTT integration config' (seed_mqtt_cfg: false)."
                log "  3. Add these commandline_options:"
                log "       --mqttjson"
                log "       --configpath=/config/ebusd-configuration/en"
                log "       --scanconfig"
                log "       --accesslevel=*"
                log "       --mqtttopic=ebusd/%circuit/%name"
                log "       --mqttvar=filter-direction=r|u|^w"
                log "  4. Restart the eBUSd add-on."
            else
                log "  - Restart the eBUSd add-on (Settings -> Apps/Add-ons -> eBUSd -> Restart) to load the updated CSVs."
            fi
        elif [ "$DETECTED_ENV" = "linux" ]; then
            log "  - Restart eBUSd: sudo systemctl restart ebusd"
        else
            log "  - Make sure eBUSd uses '--configpath=${TARGET_DIR}' and restart eBUSd."
        fi
    fi
fi
