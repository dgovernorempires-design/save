const fs = require('fs');
const { execSync } = require('child_process');
const path = require('path');

const ytDlpPath = path.join('/tmp', 'yt-dlp');

// Robustly download the official Linux binary for yt-dlp if it doesn't exist
if (!fs.existsSync(ytDlpPath)) {
    console.log("[Setup] Downloading official Linux yt-dlp binary to /tmp...");
    try {
        execSync(`curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o ${ytDlpPath}`, { stdio: 'inherit' });
        execSync(`chmod +x ${ytDlpPath}`, { stdio: 'inherit' });
        console.log("[Setup] yt-dlp successfully downloaded and configured for Linux.");
    } catch (err) {
        console.error("[Setup Error] Failed to download yt-dlp binary:", err.message);
    }
}
