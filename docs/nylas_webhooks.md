# Nylas Notetaker webhooks (media-ready notifications)

Nylas can push Notetaker status + media updates to your app using webhooks.
This is the best way to download transcripts _as soon as they are available_ without blocking the meeting-join loop.

## What you subscribe to

From Nylas notification schemas:

- `notetaker.meeting_state`: changes while the bot is trying to join / in-meeting
- `notetaker.media`: media processing updates, including when transcript becomes **available**

`notetaker.media` has a `state` field (for example: `processing`, `available`, `error`, `deleted`).
When `state` is `available`, the payload includes media URLs (including `transcript`).

## Local receiver in this repo

This repo includes a minimal webhook receiver:

- `GET /?challenge=...` responds with the challenge body (required by Nylas verification)
- `POST /` accepts webhook notifications
- verifies signatures if you set `NYLAS_WEBHOOK_SECRET`
- stores payloads under `.secrets/webhooks/`
- downloads `notetaker.media` transcript when `state=available`

Run it:

- `C:/Users/Abderrahmane/Desktop/SmartMeetOS/.venv/Scripts/python.exe -m services.tools.webhook_receiver --port 8000`

Output files:

- `.secrets/webhooks/received/*.json` (every webhook payload)
- `.secrets/webhooks/media/<notetaker_id>/transcript.json` (downloaded transcript)

## Expose the endpoint publicly (HTTPS)

Nylas requires a webhook URL that is reachable from the public internet over **HTTPS**.

Nylas notes that it blocks ngrok URLs. Recommended options include:

- VS Code port forwarding
- Hookdeck
- Any HTTPS reverse proxy you control

Once you have a public URL, set the Nylas webhook URL to:

- `https://<your-public-host>/` (the receiver uses the root path)

## Create the webhook subscription

You can create it in the Nylas Dashboard (Notifications → Create webhook), or using the Admin API:

`POST https://api.us.nylas.com/v3/webhooks/`

Body example:

- `trigger_types`: include `notetaker.media` (and optionally `notetaker.meeting_state`, `notetaker.created`, `notetaker.updated`, `notetaker.deleted`)
- `webhook_url`: your public HTTPS endpoint

The API response includes a `webhook_secret`. Save it.

## Verify webhook signatures

Nylas includes a signature header on every webhook notification:

- `x-nylas-signature` (or `X-Nylas-Signature` depending on your framework)

It is a hex-encoded HMAC-SHA256 signature of the **raw request body**, using the webhook destination’s `webhook_secret` as the key.

To enable verification in the local receiver:

- `setx NYLAS_WEBHOOK_SECRET "<webhook_secret_from_nylas>"`

Then restart the receiver.

## How this fits SmartMeetOS

Recommended production shape:

- Meeting join loop: creates notetakers, supervises join/rejoin, writes results to `.secrets/meeting_results.json`.
- Webhook receiver (this): downloads transcript/media immediately on `notetaker.media state=available`.

This avoids waiting/polling inside the supervisor and reduces the risk of blocking the next meeting.
