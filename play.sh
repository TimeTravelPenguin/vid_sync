#!/bin/bash

secs() {
  local h=$1
  local m=$2
  local s=$3
  echo $((h * 3600 + m * 60 + s))
}

# ===== Config =====

vid1="./../CDawgVODs - Continuing Dark Souls Co-op With Ironmouse! (Part 2).mp4"
vid2="./../IRONMOUSE VODS - Ironmouse & Connor Play Dark Souls Remastered (Day 2).mp4"

start1=$(secs 00 23 25)
start2=$(secs 00 54 45)

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
