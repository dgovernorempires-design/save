const express = require('express');
const axios = require('axios');
const app = express();

app.use(express.json());

// Secret security token shared between cPanel and Render
const RENDER_SECRET_TOKEN = process.env.RENDER_SECRET_TOKEN || 'YOUR_RENDER_SECRET_TOKEN';
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
    res.json({ success: true, message: `Job ${job_id} accepted for background processing.` });

    // Execute background processing asynchronously
    processMediaJob(job_id, source_target);
});

async function processMediaJob(jobId, sourceTarget) {
    console.log(`Starting processing for Job ID: ${jobId} using source: ${sourceTarget}`);

    try {
        // Step 1: Update cPanel status to 'processing'
        await notifyCPanel(jobId, 'processing');

        // [Insert your FFmpeg / yt-dlp processing logic here]
        // E.g., downloading the file from sourceTarget, slicing clips, etc.
        console.log(`Processing media stream from: ${sourceTarget}`);
        await new Promise(resolve => setTimeout(resolve, 8000)); // Simulating heavy rendering task

        // Step 2: Notify cPanel that processing has successfully completed
        await notifyCPanel(jobId, 'completed');
        console.log(`Job ID: ${jobId} completed successfully.`);

    } catch (error) {
        console.error(`Error processing Job ID ${jobId}:`, error.message);
        await notifyCPanel(jobId, 'failed');
    }
}

async function notifyCPanel(jobId, status) {
    try {
        await axios.post(CPANEL_WEBHOOK_CALLBACK, {
            job_id: jobId,
            status: status
        }, {
            headers: { 'Content-Type': 'application/json' }
        });
    } catch (err) {
        console.error(`Failed to report status back to cPanel for Job ${jobId}:`, err.message);
    }
}

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`DGovernor Render Worker running on port ${PORT}`);
});
