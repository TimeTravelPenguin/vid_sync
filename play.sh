#!/bin/bash

# ===== Config =====

vid1="./vid1.mp4"
vid2="./vid2.mp4"

start1="00h23m25s"
start2="00h54m45s"

# ==================

search_dur=30
state="./tmp/mpv_state.sh"

if [ ! -d "./tmp" ]; then
  mkdir -p ./tmp || exit 1
fi

vid1=$(realpath "$vid1")
vid2=$(realpath "$vid2")

if [ ! -f "combined.mkv" ]; then
  echo "Finding offset between videos..."
  offset=$(
    uv run ./main.py \
      --start1 "$start1" \
      --start2 "$start2" \
      --search_dur "$search_dur" \
      --silent "$vid1" "$vid2"
  ) || exit 1

  # If the offset is negative, this means vid2 starts before vid1.
  # In this case, we simply negate the offset and pad vid2 with silence.
  # If the offset is positive, then vid1 starts before vid2.
  # In this case, we swap the videos and create an offset video for vid1.
  if [[ $offset == -* ]]; then
    offset=$(awk "BEGIN { print ($offset < 0) ? -($offset) : $offset }")
  else
    vid1_temp="$vid1"
    vid1="$vid2"
    vid2="$vid1_temp"
  fi

  echo "Offset: $offset"

  echo "Creating combined video with offset..."
  ffmpeg \
    -y \
    -hide_banner \
    -loglevel error \
    -stats \
    -i "$vid1" \
    -itsoffset "$offset" -i "$vid2" \
    -map 0:v -map 0:a \
    -map 1:v -map 1:a \
    -c copy combined.mkv || exit 1
fi

echo "Playing videos with offset..."
mpv --player-operation-mode=pseudo-gui \
  --input-conf=mpv.conf \
  --save-position-on-quit \
  combined.mkv
