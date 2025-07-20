#!/bin/bash

secs() {
  local h=$1
  local m=$2
  local s=$3
  echo $((h * 3600 + m * 60 + s))
}

vid2="./../CDawgVODs - Continuing Dark Souls Co-op With Ironmouse! (Part 2).mp4"
vid1="./../IRONMOUSE VODS - Ironmouse & Connor Play Dark Souls Remastered (Day 2).mp4"

start2=$(secs 00 23 25)
start1=$(secs 00 54 45)
search_duration=30

FFMPEG_OPTS=(-hide_banner -loglevel error -stats -y)

if [ ! -f combined.mkv ]; then
  echo "Start 1: $start1"
  echo "Start 2: $start2"

  # Extract audio into wavs
  if [ ! -f clipped1.wav ]; then
    ffmpeg "${FFMPEG_OPTS[@]}" \
      -ss "$start1" \
      -t "$search_duration" \
      -i "$vid1" \
      -vn -acodec pcm_s16le \
      -ar 44100 \
      -ac 2 \
      clipped1.wav || exit 1
  fi

  if [ ! -f clipped2.wav ]; then
    ffmpeg "${FFMPEG_OPTS[@]}" \
      -ss "$start2" \
      -t "$search_duration" \
      -i "$vid2" \
      -vn -acodec pcm_s16le \
      -ar 44100 \
      -ac 2 \
      clipped2.wav || exit 1
  fi

  # Sync the audio
  val=$(uv run syncstart clipped1.wav clipped2.wav -t "$search_duration" -n -l 300 -s -q)

  # Extract the sync value
  sync_file=$(echo "$val" | cut -d ',' -f 1)
  sync_offset=$(echo "$val" | cut -d ',' -f 2)

  echo "Sync file: $sync_file"
  echo "Sync value: $sync_offset"

  echo "Creating combined video with offset..."
  # If sync_file is file2, swap the order of the inputs
  if [ "$sync_file" == "clipped1.wav" ]; then
    sync_value=$(echo "$start2 - $start1 - $sync_offset" | bc -l)
    echo "Sync value for clipped1.wav: $sync_value"

    ffmpeg "${FFMPEG_OPTS[@]}" \
      -i "$vid2" \
      -itsoffset "$sync_value" \
      -i "$vid1" \
      -map 0:v -map 0:a \
      -map 1:v -map 1:a \
      -c copy \
      combined.mkv || exit 1
  elif [ "$sync_file" == "clipped2.wav" ]; then
    sync_value=$(echo "$start1 - $start2 - $sync_offset" | bc -l)
    echo "Sync value for clipped2.wav: $sync_value"

    ffmpeg "${FFMPEG_OPTS[@]}" \
      -i "$vid1" \
      -itsoffset "$sync_value" \
      -i "$vid2" \
      -map 0:v -map 0:a \
      -map 1:v -map 1:a \
      -c copy \
      combined.mkv || exit 1
  else
    echo "Error: sync_file is neither clipped1.wav nor clipped2.wav"
    exit 1
  fi
fi

echo "Playing videos with offset..."
mpv --player-operation-mode=pseudo-gui \
  --input-conf=mpv.conf \
  --save-position-on-quit \
  combined.mkv
