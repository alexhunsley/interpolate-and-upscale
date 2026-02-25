#!/usr/bin/env zsh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  vidpipe.zsh [--interp N] [--width W] [--height H] [--scale S] [--keep] [--output_dir DIR] <input_video> [<input_video> ...]

Options:
  --interp N     Time factor. >1 slows down (uses RIFE v4 to add frames). <1 speeds up (drops frames; no RIFE). 1 = no change.
                Examples: 2.0 = 2x slower, 1.5 = 1.5x slower, 0.5 = 2x faster.
  --width W      Target width for resize (up or down). If only width or height is provided, the other is computed to preserve AR.
  --height H     Target height for resize (up or down).
  --scale S      Scale factor to multiply input width/height (e.g. 2, 0.5). Mutually exclusive with --width/--height.
  --keep         Keep intermediate folders/files.
  --output_dir DIR  Output directory (defaults to each input file's directory).
EOF
  exit 2
}

# ---- Parse args ----
interp_factor=""
want_interp=0
want_resize=0
keep=0
up_w=""
up_h=""
scale_factor=""
output_dir=""
inputs=()

while (( $# > 0 )); do
  case "$1" in
    --interp) shift || usage; interp_factor="${1:-}"; [[ -z "$interp_factor" ]] && usage; want_interp=1; shift ;;
    --width)  shift || usage; up_w="${1:-}"; [[ -z "$up_w" ]] && usage; want_resize=1; shift ;;
    --height) shift || usage; up_h="${1:-}"; [[ -z "$up_h" ]] && usage; want_resize=1; shift ;;
    --scale)  shift || usage; scale_factor="${1:-}"; [[ -z "$scale_factor" ]] && usage; want_resize=1; shift ;;
    --keep) keep=1; shift ;;
    --output_dir) shift || usage; output_dir="${1:-}"; [[ -z "$output_dir" ]] && usage; shift ;;
    --help|-h) usage ;;
    --*) print -u2 "Error: unknown option: $1"; usage ;;
    *) inputs+=("$1"); shift ;;
  esac
done

(( ${#inputs[@]} == 0 )) && usage
for in in "${inputs[@]}"; do
  [[ -f "$in" ]] || { print -u2 "Error: input file not found: $in"; exit 2; }
done

# Mutually exclusive: (--width/--height) vs --scale
if [[ -n "$scale_factor" ]] && ([[ -n "$up_w" ]] || [[ -n "$up_h" ]]); then
  print -u2 "Error: --scale is mutually exclusive with --width/--height"
  exit 2
fi

if (( ! want_interp && ! want_resize )); then
  print -u2 "Error: you must specify at least one of: --interp N, --width W, --height H, --scale S"
  usage
fi

# ---- Tools ----
ffmpeg_bin="${FFMPEG_BIN:-ffmpeg}"
ffprobe_bin="${FFPROBE_BIN:-ffprobe}"
rife_bin="${RIFE_BIN:-/Applications/rife-ncnn-vulkan-20221029-macos/rife-ncnn-vulkan}"
fx_bin="${FX_UPSCALE_BIN:-fx-upscale}"
rife_model="${RIFE_MODEL:-rife-v4}"

need_cmd() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1 && [[ "$bin" != /* || ! -x "$bin" ]]; then
    print -u2 "Error: required tool not found/executable: $bin"
    exit 2
  fi
}

need_cmd "$ffmpeg_bin"
need_cmd "$ffprobe_bin"
(( want_interp )) && need_cmd "$ffmpeg_bin"
(( want_resize )) && need_cmd "$fx_bin"

cleanup_items=()
cleanup() {
  (( keep )) && return 0
  for p in "${cleanup_items[@]}"; do
    [[ -e "$p" ]] && rm -rf -- "$p" || true
  done
}
trap cleanup EXIT

read_vid_wh() {
  local file="$1"
  local wh
  wh="$("$ffprobe_bin" -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$file" | head -n 1)"
  [[ "$wh" =~ '^[0-9]+x[0-9]+$' ]] || { print -u2 "Error: failed to probe width/height for: $file"; exit 2; }
  print "$wh"
}

read_vid_frames() {
  local file="$1"
  local n
  n="$("$ffprobe_bin" -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of default=nw=1:nk=1 "$file" | head -n 1)"
  [[ "$n" =~ '^[0-9]+$' ]] || { print -u2 "Error: failed to probe frame count for: $file"; exit 2; }
  print "$n"
}

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
  w=int(tw); h=even(w*in_h/in_w); print(f"{w} {h}")
elif th and not tw:
  h=int(th); w=even(h*in_w/in_h); print(f"{w} {h}")
else:
  raise SystemExit(2)
PY
}

compute_scaled_dim() {
  local in_w="$1" in_h="$2" scale="$3"
  python3 - <<PY
import math
in_w=int("$in_w"); in_h=int("$in_h"); s=float("$scale")
if s <= 0:
  raise SystemExit(2)
def even(x):
  x=int(round(x))
  return x if x%2==0 else x+1
w=even(in_w*s)
h=even(in_h*s)
print(f"{max(2,w)} {max(2,h)}")
PY
}

build_atempo_chain_value() {
  local tempo="$1"
  python3 - <<PY
t=float("$tempo")
parts=[]
while t < 0.5:
    parts.append("atempo=0.5"); t *= 2.0
while t > 2.0:
    parts.append("atempo=2.0"); t /= 2.0
parts.append(f"atempo={t:.10f}".rstrip('0').rstrip('.'))
print(",".join(parts))
PY
}

build_atempo_chain_ratio() {
  local in_frames="$1" out_frames="$2"
  python3 - <<PY
inf=int("$in_frames"); outf=int("$out_frames")
t = inf / outf
parts=[]
while t < 0.5:
    parts.append("atempo=0.5"); t *= 2.0
while t > 2.0:
    parts.append("atempo=2.0"); t /= 2.0
parts.append(f"atempo={t:.10f}".rstrip('0').rstrip('.'))
print(",".join(parts))
PY
}

# Validate interp factor (allows >0)
interp_mode="none"   # none | slow (RIFE) | speed (ffmpeg)
if (( want_interp )); then
  [[ "$interp_factor" =~ '^[0-9]+([.][0-9]+)?$' ]] || { print -u2 "Error: --interp must be a number (got: $interp_factor)"; exit 2; }
  python3 - <<PY
f=float("$interp_factor")
import sys
sys.exit(0 if f>0.0 else 2)
PY
  interp_mode="$(python3 - <<PY
f=float("$interp_factor")
if abs(f-1.0) < 1e-12: print("none")
elif f > 1.0: print("slow")
else: print("speed")
PY
)"
  if [[ "$interp_mode" == "slow" ]]; then
    need_cmd "$rife_bin"
  fi
fi

# Validate scale factor if provided
if [[ -n "$scale_factor" ]]; then
  [[ "$scale_factor" =~ '^[0-9]+([.][0-9]+)?$' ]] || { print -u2 "Error: --scale must be a number (got: $scale_factor)"; exit 2; }
  python3 - <<PY
s=float("$scale_factor")
import sys
sys.exit(0 if s>0.0 else 2)
PY
fi

process_one() {
  local in="$1"

  local out_dir="${output_dir:-${in:h}}"
  mkdir -p "$out_dir"

  local base="${in##*/}"
  local stem="${base%.*}"
  stem="${stem//_small_/}"

  local frames_dir="${out_dir}/frames_${stem}"
  local interp_dir="${out_dir}/frames_done_${stem}"

  local interp_out=""
  local input_for_resize="$in"

  # ---- Interp/retime stage ----
  if (( want_interp )) && [[ "$interp_mode" != "none" ]]; then
    if [[ "$interp_mode" == "speed" ]]; then
      interp_out="${out_dir}/${stem}__speed_${interp_factor}x.mp4"
      [[ -e "$interp_out" ]] && { print -u2 "Error: refusing to overwrite existing file: $interp_out"; exit 1; }
      cleanup_items+=("$interp_out")

      audio_tempo="$(python3 - <<PY
f=float("$interp_factor")
print(1.0/f)
PY
)"
      atempo_chain="$(build_atempo_chain_value "$audio_tempo")"

      print "1) Speeding video by factor ${interp_factor} (duration *= ${interp_factor}); audio tempo *= ${audio_tempo}"
      if "$ffprobe_bin" -v error -select_streams a:0 -show_entries stream=codec_type -of default=nw=1:nk=1 "$in" | grep -q "audio"; then
        "$ffmpeg_bin" -i "$in" \
          -c:v libx264 -profile:v high -level 4.2 -pix_fmt yuv420p \
          -vf "setpts=PTS*${interp_factor}" \
          -filter:a "$atempo_chain" -c:a aac -b:a 192k \
          -movflags +faststart "$interp_out"
      else
        "$ffmpeg_bin" -i "$in" \
          -c:v libx264 -profile:v high -level 4.2 -pix_fmt yuv420p \
          -vf "setpts=PTS*${interp_factor}" \
          -movflags +faststart "$interp_out"
      fi
      input_for_resize="$interp_out"

    else
      for d in "$frames_dir" "$interp_dir"; do
        [[ -e "$d" ]] && { print -u2 "Error: refusing to run because path already exists: $d"; exit 1; }
      done
      mkdir -p "$frames_dir" "$interp_dir"
      cleanup_items+=("$frames_dir" "$interp_dir")

      print "0) Counting frames (needed for exact interpolation like 1.5x)..."
      in_frames="$(read_vid_frames "$in")"
      out_frames="$(python3 - <<PY
import math
n=int("$in_frames"); f=float("$interp_factor")
m=int(math.floor(n*f + 0.5))
print(max(1, m))
PY
)"
      (( out_frames >= 2 )) || { print -u2 "Error: computed output frame count too small: $out_frames"; exit 2; }
      atempo_chain="$(build_atempo_chain_ratio "$in_frames" "$out_frames")"

      interp_out="${out_dir}/${stem}__interpolate_${interp_factor}x.mp4"
      [[ -e "$interp_out" ]] && { print -u2 "Error: refusing to overwrite existing file: $interp_out"; exit 1; }
      cleanup_items+=("$interp_out")

      print "1) Splitting video into PNG frames: $frames_dir/"
      "$ffmpeg_bin" -i "$in" -vsync 0 "${frames_dir}/%08d.png"

      print "2) Interpolating frames with RIFE model ${rife_model} to target frames ${out_frames} (from ${in_frames}): $interp_dir/"
      "$rife_bin" -m "$rife_model" -i "${frames_dir}/" -o "${interp_dir}/" -n "$out_frames"

      print "3) Reassembling interpolated video + retimed audio (atempo: $atempo_chain): $interp_out"
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

      input_for_resize="$interp_out"
    fi
  fi

  # ---- Resize stage (optional) ----
  final_out=""
  if (( want_resize )); then
    wh="$(read_vid_wh "$input_for_resize")"
    in_w="${wh%x*}"
    in_h="${wh#*x}"

    if [[ -n "$scale_factor" ]]; then
      read up_w_calc up_h_calc <<<"$(compute_scaled_dim "$in_w" "$in_h" "$scale_factor")"
      up_w="$up_w_calc"
      up_h="$up_h_calc"
    else
      read up_w_calc up_h_calc <<<"$(compute_missing_dim "$in_w" "$in_h" "$up_w" "$up_h")"
      up_w="$up_w_calc"
      up_h="$up_h_calc"
    fi

    if (( want_interp )) && [[ "$interp_mode" != "none" ]]; then
      final_out="${out_dir}/${stem}__${interp_mode}_${interp_factor}x__scaled_${up_w}x${up_h}.mp4"
    else
      final_out="${out_dir}/${stem}__scaled_${up_w}x${up_h}.mp4"
    fi

    [[ -e "$final_out" ]] && { print -u2 "Error: refusing to overwrite existing file: $final_out"; exit 1; }

    print "4) Resizing video to ${up_w}x${up_h}: $final_out"
    expected_out="${out_dir}/${input_for_resize:t:r} Upscaled.mp4"
    [[ -e "$expected_out" || -e "$final_out" ]] && {
      print -u2 "Error: refusing to overwrite existing fx-upscale output:"
      [[ -e "$expected_out" ]] && print -u2 "  $expected_out"
      [[ -e "$final_out" ]] && print -u2 "  $final_out"
      exit 1
    }

    ( cd "$out_dir" && "$fx_bin" --width "$up_w" --height "$up_h" "$input_for_resize" )

    [[ -f "$expected_out" ]] || {
      print -u2 "Error: expected fx-upscale output not found: $expected_out"
      print -u2 "Directory listing:"
      ls -la . >&2 || true
      exit 1
    }

    mv "$expected_out" "$final_out"
  else
    final_out="$interp_out"
  fi

  if [[ -z "$final_out" ]]; then
    if (( want_interp )) && [[ "$interp_mode" == "none" ]]; then
      print -u2 "Error: --interp 1 makes no change. Specify a factor != 1 and/or use --width/--height/--scale."
      exit 2
    fi
    print -u2 "Error: internal: no output produced."
    exit 2
  fi

  # If we didn't keep intermediates and no resize was requested, keep the intermediate mp4 (it's the final output)
  if (( ! keep )) && (( want_interp )) && (( ! want_resize )); then
    cleanup_items=("${(@)cleanup_items:#$final_out}")
  fi

  print "Done."
  print "Output: $final_out"
}

for in in "${inputs[@]}"; do
  process_one "$in"
done
