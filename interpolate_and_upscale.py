#!/usr/bin/env zsh
set -euo pipefail

# Video -> video pipeline (macOS)
# - Optional interpolation via RIFE-ncnn-Vulkan (--interp N)
# - Optional upscale via fx-upscale (--width W and/or --height H)
# - Defaults to deleting intermediates unless --keep is given
#
# Usage examples:
#   ./vidpipe.zsh --interp 2 input.mov
#   ./vidpipe.zsh --width 1920 input.mp4
#   ./vidpipe.zsh --height 1080 input.mp4
#   ./vidpipe.zsh --interp 2 --width 1920 --height 1080 input.mp4
#   ./vidpipe.zsh --keep --interp 3 --width 1920 input.mp4

usage() {
  cat >&2 <<'EOF'
Usage:
  vidpipe.zsh [--interp N] [--width W] [--height H] [--keep] <input_video>

Options:
  --interp N     Interpolation factor (e.g. 2). If omitted: no interpolation.
  --width W      Target width for upscaling. If only width or height is provided, the other is computed to preserve AR.
  --height H     Target height for upscaling.
  --keep         Keep intermediate folders/files (frames_*, frames_done_*, intermediate mp4).
EOF
  exit 2
}

# ---- Parse args ----
interp_factor=""
want_interp=0
want_upscale=0
keep=0
up_w=""
up_h=""
in=""

while (( $# > 0 )); do
  case "$1" in
    --interp)
      shift || usage
      interp_factor="${1:-}"
      [[ -z "$interp_factor" ]] && usage
      want_interp=1
      shift
      ;;
    --width)
      shift || usage
      up_w="${1:-}"
      [[ -z "$up_w" ]] && usage
      want_upscale=1
      shift
      ;;
    --height)
      shift || usage
      up_h="${1:-}"
      [[ -z "$up_h" ]] && usage
      want_upscale=1
      shift
      ;;
    --keep)
      keep=1
      shift
      ;;
    --help|-h)
      usage
      ;;
    --*)
      print -u2 "Error: unknown option: $1"
      usage
      ;;
    *)
      if [[ -n "$in" ]]; then
        print -u2 "Error: multiple input files provided."
        usage
      fi
      in="$1"
      shift
      ;;
  esac
done

[[ -z "$in" ]] && usage
[[ ! -f "$in" ]] && { print -u2 "Error: input file not found: $in"; exit 2; }

if (( ! want_interp && ! want_upscale )); then
  print -u2 "Error: you must specify at least one of: --interp N, --width W, --height H"
  usage
fi

# ---- Tools (env overrides) ----
ffmpeg_bin="${FFMPEG_BIN:-ffmpeg}"
ffprobe_bin="${FFPROBE_BIN:-ffprobe}"
rife_bin="${RIFE_BIN:-/Applications/rife-ncnn-vulkan-20221029-macos/rife-ncnn-vulkan}"
fx_bin="${FX_UPSCALE_BIN:-fx-upscale}"

need_cmd() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1 && [[ "$bin" != /* || ! -x "$bin" ]]; then
    print -u2 "Error: required tool not found/executable: $bin"
    exit 2
  fi
}

need_cmd "$ffmpeg_bin"
need_cmd "$ffprobe_bin"
(( want_interp )) && need_cmd "$rife_bin"
(( want_upscale )) && need_cmd "$fx_bin"

# ---- Helpers ----
cleanup_items=()

cleanup() {
  (( keep )) && return 0
  for p in "${cleanup_items[@]}"; do
    [[ -e "$p" ]] && rm -rf -- "$p" || true
  done
}
trap cleanup EXIT

# Name parts
base="${in:t}"   # filename.ext
stem="${base:r}" # filename

# Probe input dimensions for AR calculations (and for sanity)
read_vid_wh() {
  local file="$1"
  local wh
  wh="$("$ffprobe_bin" -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$file" | head -n 1)"
  if [[ ! "$wh" =~ '^[0-9]+x[0-9]+$' ]]; then
    print -u2 "Error: failed to probe width/height for: $file"
    exit 2
  fi
  print "$wh"
}

# Compute missing upscale dimension preserving AR, rounding to even (safer for H.264).
compute_missing_dim() {
  local in_w="$1" in_h="$2" target_w="$3" target_h="$4"
  python3 - <<PY
import math
in_w=int("$in_w"); in_h=int("$in_h")
tw="$target_w"; th="$target_h"
def even(x): 
  x=int(round(x))
  return x if x%2==0 else x+1
if tw and th:
  print(f"{int(tw)} {int(th)}")
elif tw and not th:
  w=int(tw)
  h=even(w*in_h/in_w)
  print(f"{w} {h}")
elif th and not tw:
  h=int(th)
  w=even(h*in_w/in_h)
  print(f"{w} {h}")
else:
  raise SystemExit(2)
PY
}

# Build atempo chain for audio slowdown: atempo = 1/interp_factor (chained into [0.5..2.0])
build_atempo_chain() {
  local factor="$1"
  python3 - <<PY
import sys
f=float("$factor")
t=1.0/f
parts=[]
while t < 0.5:
    parts.append("atempo=0.5")
    t *= 2.0
while t > 2.0:
    parts.append("atempo=2.0")
    t /= 2.0
parts.append(f"atempo={t:.10f}".rstrip('0').rstrip('.'))
print(",".join(parts))
PY
}

# Validate interp factor if used
atempo_chain=""
if (( want_interp )); then
  if [[ ! "$interp_factor" =~ '^[0-9]+([.][0-9]+)?$' ]]; then
    print -u2 "Error: --interp must be a number (got: $interp_factor)"
    exit 2
  fi
  # Must be > 1 to make sense; allow 1 but it does nothing.
  python3 - <<PY
f=float("$interp_factor")
import sys
sys.exit(0 if f>=1 else 2)
PY
  atempo_chain="$(build_atempo_chain "$interp_factor")"
fi

# Refuse to run if intermediate folders exist (only if interpolation is requested)
frames_dir="frames_${stem}"
interp_dir="frames_done_${stem}"
if (( want_interp )); then
  for d in "$frames_dir" "$interp_dir"; do
    if [[ -e "$d" ]]; then
      print -u2 "Error: refusing to run because path already exists: $d"
      exit 1
    fi
  done
fi

# Determine base input for upscale stage:
# - If we interpolate, upscale uses interpolated output
# - If no interpolate, upscale uses original input
interp_out=""
input_for_upscale="$in"

# ---- Interpolation stage (optional) ----
if (( want_interp )); then
  mkdir -p "$frames_dir" "$interp_dir"
  cleanup_items+=("$frames_dir" "$interp_dir")

  interp_out="${stem}__interpolate_${interp_factor}x.mp4"
  if [[ -e "$interp_out" ]]; then
    print -u2 "Error: refusing to overwrite existing file: $interp_out"
    exit 1
  fi
  cleanup_items+=("$interp_out")

  print "1) Splitting video into PNG frames: $frames_dir/"
  "$ffmpeg_bin" -i "$in" -vsync 0 "${frames_dir}/%08d.png"

  print "2) Interpolating frames with RIFE: $interp_dir/"
  "$rife_bin" -i "${frames_dir}/" -o "${interp_dir}/"

  print "3) Reassembling interpolated video + slowed audio (atempo: $atempo_chain): $interp_out"
  # Audio must be re-encoded for atempo; AAC-LC is compatible with macOS/iOS.
  # If input has no audio, this will fail; handle by trying without audio map.
  if "$ffprobe_bin" -v error -select_streams a:0 -show_entries stream=codec_type -of default=nw=1:nk=1 "$in" | grep -q "audio"; then
    "$ffmpeg_bin" -i "${interp_dir}/%08d.png" -i "$in" \
      -map 0:v:0 -map 1:a:0 \
      -c:v libx264 -profile:v high -level 4.2 -pix_fmt yuv420p \
      -filter:a "$atempo_chain" -c:a aac -b:a 192k \
      -movflags +faststart "$interp_out"
  else
    print "   (No audio stream detected; producing video-only output.)"
    "$ffmpeg_bin" -i "${interp_dir}/%08d.png" \
      -c:v libx264 -profile:v high -level 4.2 -pix_fmt yuv420p \
      -movflags +faststart "$interp_out"
  fi

  input_for_upscale="$interp_out"
fi

# ---- Upscale stage (optional) ----
final_out=""
if (( want_upscale )); then
  # Compute missing dimension preserving AR, based on the file being upscaled
  wh="$(read_vid_wh "$input_for_upscale")"
  in_w="${wh%x*}"
  in_h="${wh#*x}"

  read up_w_calc up_h_calc <<<"$(compute_missing_dim "$in_w" "$in_h" "$up_w" "$up_h")"
  up_w="$up_w_calc"
  up_h="$up_h_calc"

  # Output name
  if (( want_interp )); then
    final_out="${stem}__interpolate_${interp_factor}x__upscaled_${up_w}x${up_h}.mp4"
  else
    final_out="${stem}__upscaled_${up_w}x${up_h}.mp4"
  fi

  if [[ -e "$final_out" ]]; then
    print -u2 "Error: refusing to overwrite existing file: $final_out"
    exit 1
  fi

  print "4) Upscaling video to ${up_w}x${up_h}: $final_out"
  expected_upscaled="${input_for_upscale:r} Upscaled.mp4"
  if [[ -e "$expected_upscaled" || -e "$final_out" ]]; then
    print -u2 "Error: refusing to overwrite existing fx-upscale output:"
    [[ -e "$expected_upscaled" ]] && print -u2 "  $expected_upscaled"
    [[ -e "$final_out" ]] && print -u2 "  $final_out"
    exit 1
  fi

  "$fx_bin" --width "$up_w" --height "$up_h" "$input_for_upscale"

  if [[ ! -f "$expected_upscaled" ]]; then
    print -u2 "Error: expected fx-upscale output not found: $expected_upscaled"
    print -u2 "Directory listing:"
    ls -la . >&2 || true
    exit 1
  fi

  mv "$expected_upscaled" "$final_out"
else
  # If no upscale, final output is the interpolated file
  final_out="$interp_out"
fi

if [[ -z "$final_out" ]]; then
  print -u2 "Error: internal: no output produced."
  exit 2
fi

# If we didn't keep intermediates and no upscale was requested, keep the interpolated mp4 (it's the final output),
# so remove it from cleanup list.
if (( ! keep )) && (( want_interp )) && (( ! want_upscale )); then
  cleanup_items=("${(@)cleanup_items:#$interp_out}")
fi
# If we didn't keep and upscale was requested, interpolated mp4 is intermediate; keep cleanup as-is.

print "Done."
print "Output: $final_out"
