const express = require('express');
const axios = require('axios');
const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const FormData = require('form-data');

const app = express();
app.use(express.json());

// Secret security token shared between cPanel and Render (checking both 'amen' and 'RENDER_SECRET_TOKEN')
const RENDER_SECRET_TOKEN = process.env.amen || process.env.RENDER_SECRET_TOKEN || '4dd0711225b2f2f36b109557d91af48a';
const CPANEL_WEBHOOK_CALLBACK = 'https://dgovernorempire.com.ng/aishortvideo/api/webhook.php';

app.post('/process', async (req, res) => {
    const authHeader = req.headers['authorization'];
    
    // Validate authorization token
    if (!authHeader || authHeader !== `Bearer ${RENDER_SECRET_TOKEN}`) {
        return res.status(401).json({ error: 'Unauthorized webhook request.' });
    }

    const { job_id, source_target } = req.body;

    if (!job_id || !source_target) {
        return res.status(400).json({ error: 'Missing required payload parameters.' });
    }

    // Immediately respond to cPanel to free up the socket connection
    res.json({ success: true, message: `Job ${job_id} accepted for background rendering.` });

    // Execute real background processing asynchronously
    processMediaJob(job_id, source_target);
});

async function processMediaJob(jobId, sourceTarget) {
    console.log(`Starting real processing for Job ID: ${jobId} using source: ${sourceTarget}`);
    const outputFileName = `clipped_job_${jobId}.mp4`;
    const outputPath = path.join('/tmp', outputFileName);

    try {
        // Step 1: Update cPanel status to 'processing'
        await notifyCPanel(jobId, 'processing');

        // Use yt-dlp to download and cut/clip a sample segment (e.g., first 30 seconds)
        const command = `yt-dlp -f "best[ext=mp4]" --download-sections "*00:00-00:30" -o "${outputPath}" "${sourceTarget}"`;
        
        await new Promise((resolve, reject) => {
            exec(command, (error, stdout, stderr) => {
                if (error) {
                    console.error(`Exec error: ${error.message}`);
                    return reject(error);
                }
                resolve(stdout);
            });
        });

        if (!fs.existsSync(outputPath)) {
            throw new Error('Render failed to generate output file.');
        }

        console.log(`Rendering complete. Uploading file back to cPanel...`);

        // Step 2: Upload the processed physical file back to cPanel's webhook endpoint
        const form = new FormData();
        form.append('job_id', jobId);
        form.append('status', 'completed');
        form.append('video_file', fs.createReadStream(outputPath));

        await axios.post(CPANEL_WEBHOOK_CALLBACK, form, {
            headers: {
                ...form.getHeaders(),
                'Authorization': `Bearer ${RENDER_SECRET_TOKEN}`
            },
            maxContentLength: Infinity,
            maxBodyLength: Infinity
        });

        // Clean up temp file
        fs.unlinkSync(outputPath);
        console.log(`Job ID: ${jobId} successfully completed and synced with cPanel.`);

    } catch (error) {
        console.error(`Error processing Job ID ${jobId}:`, error.message);
        await notifyCPanel(jobId, 'failed');
        if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
    }
}

async function notifyCPanel(jobId, status) {
    try {
        await axios.post(CPANEL_WEBHOOK_CALLBACK, {
            job_id: jobId,
            status: status
        }, {
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${RENDER_SECRET_TOKEN}`
            }
        });
    } catch (err) {
        console.error(`Failed to report status back to cPanel for Job ${jobId}:`, err.message);
    }
}

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`DGovernor Render Worker running on port ${PORT}`);
});
