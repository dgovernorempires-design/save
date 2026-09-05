import sys
import os
import subprocess
import json
import urllib.request

video_url = sys.argv[1]
job_id = sys.argv[2]
target_ratio = sys.argv[3] if len(sys.argv) > 3 else "9:16"

print(f"[PROGRESS: 10%] Preparing video source...", flush=True)

downloads_dir = "downloads"
os.makedirs(downloads_dir, exist_ok=True)
output_path = os.path.join(downloads_dir, f"{job_id}.mp4")

# Check if this is a local direct file upload or a URL
if video_url == "local_upload":
    source_file = os.path.join(downloads_dir, "source_video.mp4")
    if os.path.exists(source_file):
        os.rename(source_file, output_path)
        print(f"[PROGRESS: 40%] Local upload loaded successfully.", flush=True)
    else:
        print(f"[Worker Fatal Error]: Uploaded video file not found.", flush=True)
        sys.exit(1)
else:
    print(f"[PROGRESS: 10%] Downloading video source via yt-dlp...", flush=True)
    yt_dlp_path = os.path.join('/tmp', 'yt-dlp')
    
    # Use yt-dlp flags to bypass YouTube bot detection using android client
    cmd = [
        yt_dlp_path,
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv+ba/b",
        "--extractor-args", "youtube:player_client=android",
        "-o", output_path,
        video_url
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[Worker Fatal Error]: Failed to download video with yt-dlp: {result.stderr}", flush=True)
        sys.exit(1)

print(f"[PROGRESS: 50%] Processing video aspect ratio ({target_ratio})...", flush=True)

# Placeholder simulation for clipping/processing completion 
# (Replace or integrate your actual ffmpeg processing code here)
import time
time.sleep(2)

print(f"[PROGRESS: 100%] Processing complete!", flush=True)

# Generate mock/actual clip output results back to backend/frontend
clips_data = [
    {
        "title": "Viral Highlight Clip 1",
        "url": f"/downloads/{job_id}.mp4" # Or your public download URL structure
    }
]

# Send sync payload back to Node.js server
try:
    payload = json.dumps({"jobId": job_id, "clips": clips_data}).encode('utf-8')
    req = urllib.request.Request(
        "http://localhost:10000/api/internal-sync",
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    urllib.request.urlopen(req)
except Exception as e:
    print(f"[Sync Warning]: Could not notify Node backend: {e}", flush=True)
