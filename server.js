const express = require('express');
const cors = require('cors');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

const app = express();
app.use(express.json());
app.use(cors());

// Configuration for your cPanel Webhook Archive Sync
const CPANEL_WEBHOOK_URL = 'https://yourdomain.com/webhook.php'; // Replace with your actual cPanel webhook URL
const WEBHOOK_SECRET = 'YOUR_SECURE_WEBHOOK_SECRET'; // Must match the secret in webhook.php

// Helper function to sync completed clips to cPanel
function syncToCpanelWebhook(jobId, clips) {
    if (!CPANEL_WEBHOOK_URL.includes('yourdomain.com')) {
        const data = JSON.stringify({ jobId, clips });
        const urlObj = new URL(CPANEL_WEBHOOK_URL);
        const lib = urlObj.protocol === 'https:' ? https : http;

        const reqOptions = {
            hostname: urlObj.hostname,
            path: urlObj.pathname,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Webhook-Secret': WEBHOOK_SECRET,
                'Content-Length': Buffer.byteLength(data)
            }
        };

        const req = lib.request(reqOptions, (res) => {
            let responseBody = '';
            res.on('data', chunk => responseBody += chunk);
            res.on('end', () => console.log(`[cPanel Sync] Job ${jobId} synced: ${responseBody}`));
        });

        req.on('error', (err) => {
            console.error(`[cPanel Sync Error] Failed to push job ${jobId}: ${err.message}`);
        });

        req.write(data);
        req.end();
    }
}

// Secure Auto-Deleting Download Stream Endpoint
app.get('/api/download/:filename', (req, res) => {
    const filename = req.params.filename;
    const safeFilename = path.basename(filename); // Prevent path traversal attacks
    const filePath = path.join(__dirname, 'outputs', safeFilename);

    if (!fs.existsSync(filePath)) {
        return res.status(404).json({ error: 'File already downloaded, deleted, or expired.' });
    }

    // Set headers to trigger a direct browser file download
    res.setHeader('Content-Disposition', `attachment; filename="${safeFilename}"`);
    res.setHeader('Content-Type', 'video/mp4');

    const fileStream = fs.createReadStream(filePath);
    fileStream.pipe(res);

    // Automatically delete the file from Render disk once download finishes or closes
    fileStream.on('close', () => {
        try {
            if (fs.existsSync(filePath)) {
                fs.unlinkSync(filePath);
                console.log(`[Cleanup] Auto-deleted downloaded file from disk: ${safeFilename}`);
            }
        } catch (err) {
            console.error(`[Cleanup Error]: ${err.message}`);
        }
    });

    fileStream.on('error', (err) => {
        console.error(`[Stream Error]: ${err.message}`);
        if (!res.headersSent) {
            res.status(500).json({ error: 'Download stream failed.' });
        }
    });
});

// In-memory store to track job progress
const jobStatuses = {};

async function ensureYtDlp() {
    const ytDlpPath = path.join('/tmp', 'yt-dlp');
    if (!fs.existsSync(ytDlpPath)) {
        console.log('[Setup] Downloading yt-dlp to /tmp...');
        return new Promise((resolve, reject) => {
            const file = fs.createWriteStream(ytDlpPath);
            https.get('https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp', (response) => {
                response.pipe(file);
                file.on('finish', () => {
                    file.close(() => {
                        fs.chmodSync(ytDlpPath, '755');
                        console.log('[Setup] yt-dlp downloaded and made executable.');
                        resolve(ytDlpPath);
                    });
                });
            }).on('error', (err) => {
                fs.unlink(ytDlpPath, () => {});
                reject(err);
            });
        });
    }
    return ytDlpPath;
}

// 1. Endpoint to start processing
app.post('/api/process-video', async (req, res) => {
    try {
        const { videoUrl, targetRatio } = req.body;
        if (!videoUrl) return res.status(400).json({ error: 'Video URL is required' });

        const jobId = 'job_' + Date.now();
        jobStatuses[jobId] = { progress: 5, message: 'Initializing job...' };
        
        console.log(`[Job Queued] ID: ${jobId} | Target: ${videoUrl}`);
        await ensureYtDlp();

        // Spawn Python worker
        const pythonProcess = spawn('python3', ['processor.py', videoUrl, jobId, targetRatio || '9:16']);

        pythonProcess.stdout.on('data', (data) => {
            const output = data.toString().trim();
            console.log(`[Python ${jobId}]: ${output}`);

            // Look for progress tags sent by python e.g. [PROGRESS: 45%]
            const match = output.match(/\[PROGRESS:\s*(\d+)%\]/);
            if (match) {
                const percent = parseInt(match[1]);
                jobStatuses[jobId] = { progress: percent, message: output };
            }
        });

        pythonProcess.stderr.on('data', (data) => {
            console.error(`[Python Error ${jobId}]: ${data.toString().trim()}`);
        });

        pythonProcess.on('close', (code) => {
            if (code === 0) {
                const outputDir = path.join(__dirname, 'outputs');
                let generatedClips = [];

                if (fs.existsSync(outputDir)) {
                    const files = fs.readdirSync(outputDir);
                    // Explicitly filter for captioned files to prevent mismatch errors
                    generatedClips = files
                        .filter(file => file.includes(jobId) && file.endsWith('_captioned.mp4'))
                        .map((file, index) => ({
                            title: `Viral Short Clip #${index + 1}`,
                            url: `${req.protocol}://${req.get('host')}/api/download/${file}`
                        }));
                }

                // Push completed job payload to your cPanel archive automatically
                syncToCpanelWebhook(jobId, generatedClips);

                jobStatuses[jobId] = { 
                    progress: 100, 
                    message: 'Processing complete!', 
                    status: 'completed',
                    clips: generatedClips
                };
            } else {
                jobStatuses[jobId] = { progress: 100, message: 'Processing failed.', status: 'failed' };
            }
        });

        return res.status(202).json({ success: true, jobId: jobId });

    } catch (error) {
        console.error('Queue Error:', error);
        return res.status(500).json({ error: error.message });
    }
});

// 2. Status Endpoint with Disk Fallback Recovery
app.get('/api/job-status/:jobId', (req, res) => {
    const { jobId } = req.params;
    let job = jobStatuses[jobId];

    // If job was wiped from memory due to server restart, check disk storage
    if (!job) {
        const outputDir = path.join(__dirname, 'outputs');
        if (fs.existsSync(outputDir)) {
            const files = fs.readdirSync(outputDir);
            const matchingFiles = files.filter(file => file.includes(jobId) && file.endsWith('_captioned.mp4'));
            
            if (matchingFiles.length > 0) {
                job = {
                    progress: 100,
                    message: 'Processing complete (Restored from server storage)!',
                    status: 'completed',
                    clips: matchingFiles.map((file, index) => ({
                        title: `Viral Short Clip #${index + 1}`,
                        url: `${req.protocol}://${req.get('host')}/api/download/${file}`
                    }))
                };
                jobStatuses[jobId] = job; // Re-cache in memory
            }
        }
    }

    if (!job) {
        return res.status(404).json({ error: 'Job not found or expired.' });
    }

    return res.json(job);
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, async () => {
    console.log(`Backend bridge running on port ${PORT}`);
    try { await ensureYtDlp(); } catch (e) {}
});
