#!/usr/bin/env zsh
set -euo pipefail

# Usage: ./interpolate_then_upscale.zsh /path/to/input.(mp4|mov|...)
# Requires: ffmpeg, RIFE-ncnn-Vulkan, fx-upscale
#
# Controls (optional env vars):
#   INTERP_FACTOR=2            # how many times slower/longer the interpolated video becomes (2 for 2x interpolation)
#   UPSCALE_W=1920 UPSCALE_H=1080
#   FFMPEG_BIN=ffmpeg RIFE_BIN=/path/to/rife-ncnn-vulkan FX_UPSCALE_BIN=fx-upscale

if (( $# != 1 )); then
  print -u2 "Usage: $0 <input_video>"
  exit 2
fi

in="$1"
if [[ ! -f "$in" ]]; then
  print -u2 "Error: input file not found: $in"
  exit 2
fi

# Parameters
interp_factor="${INTERP_FACTOR:-3}"
up_w="${UPSCALE_W:-928}"
up_h="${UPSCALE_H:-1376}"

# Tools
ffmpeg_bin="${FFMPEG_BIN:-ffmpeg}"
rife_bin="${RIFE_BIN:-/Applications/rife-ncnn-vulkan-20221029-macos/rife-ncnn-vulkan}"
fx_bin="${FX_UPSCALE_BIN:-fx-upscale}"

for bin in "$ffmpeg_bin" "$rife_bin" "$fx_bin"; do
  if ! command -v "$bin" >/dev/null 2>&1 && [[ "$bin" != /* || ! -x "$bin" ]]; then
    print -u2 "Error: required tool not found/executable: $bin"
    exit 2
  fi
done

# Validate INTERP_FACTOR
if [[ ! "$interp_factor" =~ '^[0-9]+([.][0-9]+)?$' ]] || (( $(printf "%.0f" "$interp_factor") < 1 )); then
  print -u2 "Error: INTERP_FACTOR must be a number >= 1 (got: $interp_factor)"
  exit 2
fi

# Build an atempo filter chain that supports values outside 0.5..2.0 by chaining.
# We want to SLOW audio to match longer video => atempo = 1 / interp_factor.
# For 2x -> 0.5. For 4x -> 0.25 => "atempo=0.5,atempo=0.5".
atempo_chain=""
atempo_target="$(python3 - <<PY
import math
f=float("$interp_factor")
print(1.0/f)
PY
)"

# Construct chain (prefer exact halves for <0.5)
remaining="$atempo_target"
chain_parts=()

python3 - <<'PY' "$atempo_target"
import sys, math
t=float(sys.argv[1])
parts=[]
# FFmpeg atempo supports 0.5..2.0 per filter.
# For slowdown <0.5, keep halving with atempo=0.5 until remaining is within [0.5,2.0]
while t < 0.5:
    parts.append("atempo=0.5")
    t *= 2.0
# For speedup >2.0 (unlikely here), keep doubling with atempo=2.0
while t > 2.0:
    parts.append("atempo=2.0")
    t /= 2.0
parts.append(f"atempo={t:.10f}".rstrip('0').rstrip('.'))
print(",".join(parts))
PY
atempo_chain="$(python3 - <<'PY' "$atempo_target"
import sys, math
t=float(sys.argv[1])
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
)"

# Name parts
base="${in:t}"          # filename.ext
stem="${base:r}"        # filename

frames_dir="frames_${stem}"
interp_dir="frames_done_${stem}"

# Refuse to run if folders already exist
for d in "$frames_dir" "$interp_dir"; do
  if [[ -e "$d" ]]; then
    print -u2 "Error: refusing to run because path already exists: $d"
    exit 1
  fi
done

mkdir -p "$frames_dir" "$interp_dir"

# Output names
interpolated_mp4="${stem}__interpolate_${interp_factor}x.mp4"
upscaled_mp4="${stem}__interpolate_${interp_factor}x__upscaled.mp4"

if [[ -e "$interpolated_mp4" || -e "$upscaled_mp4" ]]; then
  print -u2 "Error: refusing to overwrite existing output file(s):"
  [[ -e "$interpolated_mp4" ]] && print -u2 "  $interpolated_mp4"
  [[ -e "$upscaled_mp4" ]] && print -u2 "  $upscaled_mp4"
  exit 1
fi

print "1) Splitting video into PNG frames: $frames_dir/"
"$ffmpeg_bin" -i "$in" -vsync 0 "${frames_dir}/%08d.png"

print "2) Interpolating frames with RIFE: $interp_dir/"
"$rife_bin" -i "${frames_dir}/" -o "${interp_dir}/"

print "3) Reassembling interpolated video + slowed audio (atempo: $atempo_chain): $interpolated_mp4"
# Note: audio is re-encoded (required for atempo). AAC-LC is broadly compatible with macOS/iOS.
"$ffmpeg_bin" -i "${interp_dir}/%08d.png" -i "$in" \
  -map 0:v:0 -map 1:a:0 \
  -c:v libx264 -profile:v high -level 4.2 -pix_fmt yuv420p \
  -filter:a "$atempo_chain" -c:a aac -b:a 192k \
  -movflags +faststart "$interpolated_mp4"

print "4) Upscaling interpolated video to ${up_w}x${up_h}: $upscaled_mp4"
expected_upscaled="${interpolated_mp4:r} Upscaled.mp4"
if [[ -e "$expected_upscaled" || -e "$upscaled_mp4" ]]; then
  print -u2 "Error: refusing to overwrite existing fx-upscale output:"
  [[ -e "$expected_upscaled" ]] && print -u2 "  $expected_upscaled"
  [[ -e "$upscaled_mp4" ]] && print -u2 "  $upscaled_mp4"
  exit 1
fi
"$fx_bin" --width "$up_w" --height "$up_h" "$interpolated_mp4"
if [[ ! -f "$expected_upscaled" ]]; then
  print -u2 "Error: expected fx-upscale output not found: $expected_upscaled"
  print -u2 "Directory listing:"
  ls -la . >&2 || true
  exit 1
fi
mv "$expected_upscaled" "$upscaled_mp4"

print "Done."
print "Output: $upscaled_mp4"
