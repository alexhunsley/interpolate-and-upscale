# Interpolate and upscale (Mac OS)
 
Helper script for convenient upscale and/or frame interpolation of videos (Mac OS).

It can handle reduction of resolution and frames (as well as increase, obviously).

It uses [fx-upscale](https://github.com/searchinglokesh/RIFE-Official) for upscaling and [RIFE](https://github.com/searchinglokesh/RIFE-Official)  for frame interpolation.

# Setup

1. Install [fx-upscale](https://github.com/searchinglokesh/RIFE-Official):

```console
brew install fx-upscale
```

2. Install [RIFE](https://github.com/searchinglokesh/RIFE-Official) according to their [instructions](https://github.com/searchinglokesh/RIFE-Official?tab=readme-ov-file#installation).

3. Put `interpolate_and_upscale.zsh` somewhere on your path

# Examples

Upscale a video 2x and interpolate frames 2x:

```console
interpolate_and_upscale.zsh --scale 2 --interp 2 input_vid.mp4
```

Downscale a video 50%:

```console
interpolate_and_upscale.zsh --scale 0.5 input_vid.mp4
```

Interpolate a video 1.5x:

```console
interpolate_and_upscale.zsh --interp 1.5 input_vid.mp4
```

You can also specify just one of width or height for scaling and the aspect ratio of the video will be preserved:

```console
interpolate_and_upscale.zsh --height 1440 input_vid.mp4
```

Note that this script will never overwrite your source video.

# Usage

```console
Usage:
  vidpipe.zsh [--interp N] [--width W] [--height H] [--scale S] [--keep] [--output_dir DIR] <input_video> [<input_video> ...]

Options:
  --interp N        Time factor. >1 slows down (uses RIFE v4 to add frames). <1 speeds up (drops frames; no RIFE). 1 = no change.
                    Examples: 2.0 = 2x slower, 1.5 = 1.5x slower, 0.5 = 2x faster.
  --width W         Target width for resize (up or down). If only width or height is provided, the other is computed to preserve AR.
  --height H        Target height for resize (up or down).
  --scale S         Scale factor to multiply input width/height (e.g. 2, 0.5). Mutually exclusive with --width/--height.
  --keep            Keep intermediate folders/files.
  --output_dir DIR  Output directory (defaults to each input file's directory).
```

# Note on ordering

When you do both interpolation and upscaling this script runs the frame interpolation first. This is probably going to give better results than interpolating a larger source video.

# Future

This script could work on Windows with a little fiddling if you have ZSH shell support. Maybe.

Conversion to Python might be a better gambit!


