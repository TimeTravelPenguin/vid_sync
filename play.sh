vid1="./vid1.mp4"
vid2="./vid2.mp4"
vid2_offset="./video2_offset.mp4"

start1="00h23m25s"
start2="00h54m45s"
search_dur=30

# If offset video does not exist, create it
if [ ! -f "$vid2_offset" ]; then
  echo "Finding offset between videos..."
  offset=$(
    uv run --project ./main.py \
      --start1 "$start1" \
      --start2 "$start2" \
      --search_dur "$search_dur" \
      --silent "$vid1" "$vid2"
  ) || exit 1

  echo "Offset: $offset"
  ffmpeg -ss "$offset" -i "$vid2" -c copy "$vid2_offset" || exit 1
fi

mpv "$vid1" --player-operation-mode=pseudo-gui \
  --input-conf=mpv.conf \
  --save-position-on-quit \
  --external-file="$vid2_offset" \
  --lavfi-complex="[vid1][vid2]streamselect=inputs=2:map=0[vo]"
