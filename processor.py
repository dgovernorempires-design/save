import sys
import os
import subprocess
import json
import urllib.request

video_url = sys.argv[1]
job_id = sys.argv[2]
top_text = sys.argv[3] if len(sys.argv) > 3 else "MUST WATCH MOMENT"
top_bg = sys.argv[4] if len(sys.argv) > 4 else "red"
bottom_text = sys.argv[5] if len(sys.argv) > 5 else "@DgovernorEmpire"
bottom_bg = sys.argv[6] if len(sys.argv) > 6 else "green"

print(f"[PROGRESS: 10%] Initializing 3-Section Pro Studio Renderer...", flush=True)

downloads_dir = "downloads"
os.makedirs(downloads_dir, exist_ok=True)
source_path = os.path.join(downloads_dir, f"source_{job_id}.mp4")

# Download Source Video
if video_url == "local_upload":
    local_source = os.path.join(downloads_dir, f"source_{job_id}.mp4")
    if os.path.exists(local_source):
        source_path = local_source
    else:
        # Fallback to legacy path
        legacy_source = os.path.join(downloads_dir, "source_video.mp4")
        if os.path.exists(legacy_source):
            source_path = legacy_source
else:
    print(f"[PROGRESS: 20%] Downloading source video via yt-dlp...", flush=True)
    yt_dlp_path = os.path.join('/tmp', 'yt-dlp')
    cmd = [
        yt_dlp_path,
        "--extractor-args", "youtube:player_client=android,web",
        "-f", "b[ext=mp4]/b",
        "-o", source_path,
        video_url
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[Worker Fatal Error]: Download failed: {res.stderr}", flush=True)
        sys.exit(1)

print(f"[PROGRESS: 40%] Assembling 3-Section Pro Template Layout...", flush=True)

clip_filename = f"{job_id}_framed_short.mp4"
clip_output_path = os.path.join(downloads_dir, clip_filename)
thumb_filename = f"{job_id}_thumb.jpg"
thumb_output_path = os.path.join(downloads_dir, thumb_filename)

# FFmpeg Complex Filter Graph: 3-Section layout (Top Header, Center Framed Video, Bottom Branding)
filter_complex = (
    "[0:v]scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080[mid_vid];"
    "color=c=0x111827:s=1080:200[top_box];"
    "color=c=0x0f172a:s=1080:640[bot_box];"
    "[top_box]drawtext=text='{top_text}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2[top_final];"
    "[bot_box]drawtext=text='{bottom_text}':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=(h-text_h)/2[bot_final];"
    "[mid_vid]drawtext=text='Exact Spoken Subtitles...':fontcolor=yellow:fontsize=36:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-100[mid_sub];"
    "[top_final][mid_sub][bot_final]vstack=inputs=3[v]"
).format(top_text=top_text, bottom_text=bottom_text)

print(f"[PROGRESS: 70%] Rendering final composite 9:16 video...", flush=True)

ffmpeg_cmd = [
    "ffmpeg", "-y",
    "-ss", "5",
    "-i", source_path,
    "-t", "25",
    "-filter_complex", filter_complex,
    "-map", "[v]",
    "-map", "0:a?",
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
    "-c:a", "aac", "-b:a", "96k",
    clip_output_path
]

proc = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)

clips_data = []
if proc.returncode == 0:
    # Thumbnail capture
    thumb_cmd = ["ffmpeg", "-y", "-ss", "3", "-i", clip_output_path, "-vframes", "1", thumb_output_path]
    subprocess.run(thumb_cmd, capture_output=True, text=True)

    clips_data.append({
        "title": "Pro Framed Short (3-Section Layout)",
        "url": f"/downloads/{clip_filename}",
        "thumbnail": f"/downloads/{thumb_filename}"
    })
    print(f"[PROGRESS: 100%] Rendering successfully finished!", flush=True)
else:
    print(f"[FFmpeg Error]: {proc.stderr}", flush=True)

# Sync results back to Node.js backend
try:
    payload = json.dumps({"jobId": job_id, "clips": clips_data}).encode('utf-8')
    req = urllib.request.Request(
        "http://localhost:10000/api/internal-sync",
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    urllib.request.urlopen(req)
except Exception as e:
    print(f"[Sync Warning]: {e}", flush=True)
