#!/usr/bin/env zsh
set -euo pipefail

# Creates a 2s, 30fps, 640x480 test video with timestamp + frame number burned in.
# Output: test_timestamp_frameno_640x480_30fps_2s.mp4
# Requires: ffmpeg

out="test_timestamp_frameno_640x480_30fps_2s.mp4"

ffmpeg -y \
  -f lavfi -i "color=c=black:s=640x480:r=30:d=2" \
  -vf "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:fontsize=28:fontcolor=white:x=20:y=20:text='TIME %{pts\\:hms}',drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:fontsize=28:fontcolor=white:x=20:y=70:text='FRAME %{n}'" \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart \
  "$out"

print "Wrote: $out"
