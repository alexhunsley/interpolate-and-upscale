#!/usr/bin/env zsh
set -euo pipefail

# Usage: ./interpolate_then_upscale.zsh /path/to/input.(mp4|mov|...)
# Requires: ffmpeg, RIFE-ncnn-Vulkan, fx-upscale

if (( $# != 1 )); then
  print -u2 "Usage: $0 <input_video>"
  exit 2
fi

in="$1"
if [[ ! -f "$in" ]]; then
  print -u2 "Error: input file not found: $in"
  exit 2
fi

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
interpolated_mp4="${stem}__interpolate_2x.mp4"
upscaled_mp4="${stem}__interpolate_2x__upscaled.mp4"

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

print "3) Reassembling interpolated video with original audio: $interpolated_mp4"
# -framerate 60
"$ffmpeg_bin" -i "${interp_dir}/%08d.png" -i "$in" -map 0:v:0 -map 1:a:0 -c:v libx264 -profile:v high -level 4.2 -pix_fmt yuv420p -c:a copy -movflags +faststart "$interpolated_mp4"

print "4) Upscaling interpolated video to 1920x1080: $upscaled_mp4"
"$fx_bin" --width 928 --height 1376 "$interpolated_mp4"
# 1920 1080

print "Done."
print "Output: $upscaled_mp4"
