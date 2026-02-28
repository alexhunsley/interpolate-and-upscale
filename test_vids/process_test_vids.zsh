#!/bin/zsh

script_dir="${0:A:h}"

interp_cmd="$script_dir/../interpolate_and_upscale.zsh"

output_dir="output_videos/"
[[ -d "$output_dir" ]] && rm -rf -- "$output_dir"

input_video="$script_dir/test_interp_upscale_stress_640x480_30fps_2s.mp4"
[[ -e "$input_video" ]] || "$script_dir/create_test_video.zsh"

## SCALING ONLY

echo Video 1

# aspect preserving scale (smaller)
"$interp_cmd" --output_dir "$output_dir" --scale 0.5 "$input_video"

echo Video 2

# aspect preserving scale (larger)
"$interp_cmd" --output_dir "$output_dir" --scale 2 "$input_video"

echo Video 3

# aspect preserving scale (smaller) with target height
"$interp_cmd" --output_dir "$output_dir" --height 100 "$input_video"

echo Video 4

# aspect preserving scale (larger) with target width
"$interp_cmd" --output_dir "$output_dir" --width 960 "$input_video"

echo Video 5

# arbitrary scale (changes aspect ratio)
"$interp_cmd" --output_dir "$output_dir" --width 200 --height 200 "$input_video"


## INTERPOLATE ONLY

echo Video 6

# double the frames
"$interp_cmd" --output_dir "$output_dir" --interp 2 "$input_video"

echo Video 7

# half the frames
"$interp_cmd" --output_dir "$output_dir" --interp 0.5 "$input_video"


## SCALING AND INTERPOLATION

echo Video 8

# double the frames, aspect preserving scale (larger)
"$interp_cmd" --output_dir "$output_dir" --interp 2 --scale 2 "$input_video"

echo Video 9

# double the frames, aspect preserving scale (smaller)
"$interp_cmd" --output_dir "$output_dir" --interp 2 --scale 0.4 "$input_video"

echo Video 10

# double the frames, aspect preserving scale (larger) with target height
"$interp_cmd" --output_dir "$output_dir" --interp 2 --height 1000 "$input_video"

echo Video 11

# half the frames, aspect preserving scale (smaller) with target width
"$interp_cmd" --output_dir "$output_dir" --interp 0.5 --width 180 "$input_video"
