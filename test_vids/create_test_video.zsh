ffmpeg -y \
  -f lavfi -i "testsrc2=s=640x480:r=30:d=2" \
  -vf "\
drawgrid=w=40:h=40:t=1:c=white@0.4,\
rotate=0.3*t:fillcolor=black,\
noise=alls=8:allf=t,\
drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:fontsize=26:fontcolor=white:x=20+10*sin(2*PI*t):y=20+10*cos(2*PI*t):text='TIME %{pts\\:hms}',\
drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:fontsize=26:fontcolor=white:x=20:y=70:text='FRAME %{n}'" \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart \
  test_interp_upscale_stress_640x480_30fps_2s.mp4
