const express = require('express');
const cors = require('cors');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');

const app = express();
app.use(express.json());
app.use(cors());

// Serve generated video outputs statically so links are accessible
app.use('/outputs', express.static(path.join(__dirname, 'outputs')));

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
                    generatedClips = files
                        .filter(file => file.includes(jobId))
                        .map((file, index) => ({
                            title: `Viral Short Clip #${index + 1}`,
                            url: `${req.protocol}://${req.get('host')}/outputs/${file}`
                        }));
                }

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
            const matchingFiles = files.filter(file => file.includes(jobId));
            
            if (matchingFiles.length > 0) {
                job = {
                    progress: 100,
                    message: 'Processing complete (Restored from server storage)!',
                    status: 'completed',
                    clips: matchingFiles.map((file, index) => ({
                        title: `Viral Short Clip #${index + 1}`,
                        url: `${req.protocol}://${req.get('host')}/outputs/${file}`
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
