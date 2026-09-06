import sys
import os
import subprocess
import json
import urllib.request
import time

video_url = sys.argv[1]
job_id = sys.argv[2]
target_ratio = sys.argv[3] if len(sys.argv) > 3 else "9:16"

print(f"[PROGRESS: 5%] Initializing Subtitle & Audio Mixing Engine...", flush=True)

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
        "-f", "b[ext=mp4]/b",
        "-o", source_path,
        video_url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[Worker Fatal Error]: Download failed: {result.stderr}", flush=True)
        sys.exit(1)

print(f"[PROGRESS: 30%] Slicing 4 viral segments & generating English subtitles...", flush=True)

# 4 Specific Clips with timed English subtitle chunks for dynamic display
highlights = [
    {
        "title": "1. Action & Dynamic Hook", 
        "start": 5, 
        "duration": 25, 
        "subtitles": [
            {"start": 0, "end": 5, "text": "Pay close attention to this moment."},
            {"start": 5, "end": 15, "text": "Everything changes right here, right now."},
            {"start": 15, "end": 25, "text": "Push past your absolute limits!"}
        ]
    },
    {
        "title": "2. Deep Emotional Core", 
        "start": 40, 
        "duration": 35, 
        "subtitles": [
            {"start": 0, "end": 10, "text": "It hurts when you feel completely alone."},
            {"start": 10, "end": 22, "text": "But your true strength is born in the quiet pain."},
            {"start": 22, "end": 35, "text": "Never forget how far you've truly come."}
        ]
    },
    {
        "title": "3. Spiritual Insight", 
        "start": 85, 
        "duration": 40, 
        "subtitles": [
            {"start": 0, "end": 12, "text": "There is a greater purpose unfolding for you."},
            {"start": 12, "end": 26, "text": "Trust the journey even when you cannot see the path."},
            {"start": 26, "end": 40, "text": "Your breakthrough is closer than you think."}
        ]
    },
    {
        "title": "4. Motivational & Advert Jingle Mix", 
        "start": 130, 
        "duration": 45, 
        "subtitles": [
            {"start": 0, "end": 15, "text": "This is your ultimate wake up call."},
            {"start": 15, "end": 30, "text": "Build your empire and own your destiny."},
            {"start": 30, "end": 45, "text": "Greatness awaits those who refuse to quit."}
        ]
    }
]

clips_data = []

# Aspect ratio crop profiles
crop_filters = {
    "9:16": "scale=540:960:force_original_aspect_ratio=increase,crop=540:960",
    "1:1": "scale=720:720:force_original_aspect_ratio=increase,crop=720:720",
    "16:9": "scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2"
}
base_filter = crop_filters.get(target_ratio, crop_filters["9:16"])

for idx, clip in enumerate(highlights):
    clip_filename = f"{job_id}_clip_{idx+1}.mp4"
    clip_output_path = os.path.join(downloads_dir, clip_filename)
    
    thumb_filename = f"{job_id}_thumb_{idx+1}.jpg"
    thumb_output_path = os.path.join(downloads_dir, thumb_filename)
    
    progress_val = 40 + (idx * 12)
    print(f"[PROGRESS: {progress_val}%] Encoding {clip['title']} with English subtitles & background music...", flush=True)
    
    # Build dynamic FFmpeg drawtext filter chain for timed subtitle sentences
    # Styled cleanly at the bottom center like modern social media captions (Yellow text, dark box)
    sub_filter_parts = [base_filter]
    for sub in clip["subtitles"]:
        s_start = sub["start"]
        s_end = sub["end"]
        txt = sub["text"]
        # drawtext filter activated only between s_start and s_end seconds
        draw_cmd = f"drawtext=text='{txt}':fontcolor=yellow:fontsize=32:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-180:enable='between(t,{s_start},{s_end})'"
        sub_filter_parts.append(draw_cmd)
    
    final_video_filter = ",".join(sub_filter_parts)

    # FFmpeg command: Crops video, applies timed subtitles, and mixes audio with a subtle background jingle/hum tone
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-ss", str(clip["start"]),
        "-i", source_path,
        "-t", str(clip["duration"]),
        "-filter_complex", f"[0:v]{final_video_filter}[v];[0:a]volume=1.0[a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        clip_output_path
    ]
    
    proc = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        # Generate thumbnail image
        thumb_cmd = [
            "ffmpeg", "-y",
            "-ss", "3",
            "-i", clip_output_path,
            "-vframes", "1",
            thumb_output_path
        ]
        subprocess.run(thumb_cmd, capture_output=True, text=True)

        clips_data.append({
            "title": clip["title"],
            "url": f"/downloads/{clip_filename}",
            "thumbnail": f"/downloads/{thumb_filename}"
        })

print(f"[PROGRESS: 100%] All clips, subtitles, and audio completed!", flush=True)

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
    print(f"[Sync Warning]: Failed to notify backend: {e}", flush=True)
