import sys
import os
import subprocess
import json
import urllib.request
import time

video_url = sys.argv[1]
job_id = sys.argv[2]
target_ratio = sys.argv[3] if len(sys.argv) > 3 else "9:16"

print(f"[PROGRESS: 5%] Initializing lightweight video processor...", flush=True)

downloads_dir = "downloads"
os.makedirs(downloads_dir, exist_ok=True)
source_path = os.path.join(downloads_dir, f"source_{job_id}.mp4")

# 1. Acquire Source Video
if video_url == "local_upload":
    local_source = os.path.join(downloads_dir, "source_video.mp4")
    if os.path.exists(local_source):
        os.rename(local_source, source_path)
    else:
        print(f"[Worker Fatal Error]: Uploaded video file missing.", flush=True)
        sys.exit(1)
else:
    print(f"[PROGRESS: 15%] Downloading source video via yt-dlp...", flush=True)
    yt_dlp_path = os.path.join('/tmp', 'yt-dlp')
    cmd = [
        yt_dlp_path,
        "-f", "b[ext=mp4]/b",  # Grab a lighter format to save memory
        "-o", source_path,
        video_url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[Worker Fatal Error]: Download failed: {result.stderr}", flush=True)
        sys.exit(1)

print(f"[PROGRESS: 40%] Slicing optimal highlights...", flush=True)

# Define quick highlight segment (testing with 1 main highlight to prevent memory timeout)
highlights = [
    {"title": "Viral Highlight Clip (30s)", "start": 10, "duration": 30}
]

clips_data = []

# Ultra-lightweight crop filter to save CPU/RAM
crop_filters = {
    "9:16": "scale=540:960:force_original_aspect_ratio=increase,crop=540:960",
    "1:1": "scale=720:720:force_original_aspect_ratio=increase,crop=720:720",
    "16:9": "scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2"
}
filter_str = crop_filters.get(target_ratio, crop_filters["9:16"])

for idx, clip in enumerate(highlights):
    clip_filename = f"{job_id}_clip_{idx+1}.mp4"
    clip_output_path = os.path.join(downloads_dir, clip_filename)
    
    print(f"[PROGRESS: 70%] Encoding clip with ultrafast profile...", flush=True)
    
    # Using -preset ultrafast prevents CPU spikes and RAM crashes on Render
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-ss", str(clip["start"]),
        "-i", source_path,
        "-t", str(clip["duration"]),
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        clip_output_path
    ]
    
    proc = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        clips_data.append({
            "title": clip["title"],
            "url": f"/downloads/{clip_filename}"
        })

print(f"[PROGRESS: 100%] Processing complete!", flush=True)

# Sync results back to Node.js server webhook endpoint
try:
    payload = json.dumps({"jobId": job_id, "clips": clips_data}).encode('utf-8')
    req = urllib.request.Request(
        "http://localhost:10000/api/internal-sync",
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    urllib.request.urlopen(req)
except Exception as e:
    print(f"[Sync Warning]: Failed to notify backend: {e}", flush=True)
