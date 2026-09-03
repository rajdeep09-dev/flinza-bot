/**
 * Flinza Works — Cloudflare Inbound Email Routing Worker
 * Inspired by hieunc229/mailflare & 0xdps/emailflare
 * 
 * Runs on Cloudflare's 100% FREE Workers Tier (100,000 req/day free).
 * Captures all incoming emails sent to your custom domain aliases (e.g., alex@magicfitpartners.com)
 * and delivers them in real-time to Flinza's Inbound Webhook:
 * POST https://your-flinza-domain.com/api/webhooks/inbound
 * 
 * Optionally forwards a copy to your master personal Gmail inbox.
 */

export default {
  async email(message, env, ctx) {
    const fromAddress = message.from;
    const toAddress = message.to;
    const subject = message.headers.get("subject") || "(No Subject)";
    const messageId = message.headers.get("message-id") || "";
    const inReplyTo = message.headers.get("in-reply-to") || "";
    const date = message.headers.get("date") || new Date().toISOString();

    // 1. Read raw MIME email stream
    const rawEmail = await new Response(message.raw).text();

    // 2. Parse plain text and HTML body parts from MIME
    const { textBody, htmlBody } = parseMimeBody(rawEmail);

    // 3. Construct payload for Flinza Inbound Webhook
    const payload = {
      from: fromAddress,
      to: toAddress,
      subject: subject,
      body: textBody || htmlBody || "(No message body content)",
      html: htmlBody,
      message_id: messageId,
      in_reply_to: inReplyTo,
      date: date,
    };

    // 4. Dispatch webhook to Flinza
    const webhookUrl = env.FLINZA_WEBHOOK_URL || "http://localhost:8000/api/webhooks/inbound";
    const webhookSecret = env.FLINZA_WEBHOOK_SECRET || "flinza_cf_inbound_secret_2026";

    try {
      const resp = await fetch(webhookUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-webhook-secret": webhookSecret,
          "User-Agent": "Flinza-Cloudflare-Email-Worker/1.0",
        },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        console.error(`Flinza webhook returned error status ${resp.status}: ${await resp.text()}`);
      } else {
        console.log(`Successfully dispatched inbound email from ${fromAddress} to Flinza`);
      }
    } catch (err) {
      console.error(`Failed to post to Flinza webhook: ${err.message}`);
    }

    // 5. Optional: Forward copy to personal Gmail inbox if configured
    if (env.FORWARD_TO) {
      try {
        await message.forward(env.FORWARD_TO);
        console.log(`Forwarded copy to ${env.FORWARD_TO}`);
      } catch (fwdErr) {
        console.warn(`Forwarding failed: ${fwdErr.message}`);
      }
    }
  },
};

/**
 * Lightweight MIME body parser
 */
function parseMimeBody(rawMime) {
  let textBody = "";
  let htmlBody = "";

  // Split headers and body
  const headerEndIdx = rawMime.indexOf("\r\n\r\n");
  const altHeaderEndIdx = rawMime.indexOf("\n\n");
  const splitIdx = headerEndIdx !== -1 ? headerEndIdx + 4 : (altHeaderEndIdx !== -1 ? altHeaderEndIdx + 2 : 0);
  const bodyContent = rawMime.slice(splitIdx);

  // Check for multipart boundaries
  const boundaryMatch = rawMime.match(/boundary="?([^"\r\n]+)"?/i);
  if (boundaryMatch && boundaryMatch[1]) {
    const boundary = boundaryMatch[1];
    const parts = bodyContent.split(`--${boundary}`);

    for (const part of parts) {
      if (part.includes("Content-Type: text/plain") || part.includes("content-type: text/plain")) {
        const pSplit = part.indexOf("\r\n\r\n") !== -1 ? part.indexOf("\r\n\r\n") + 4 : part.indexOf("\n\n") + 2;
        textBody = part.slice(pSplit).trim();
      } else if (part.includes("Content-Type: text/html") || part.includes("content-type: text/html")) {
        const pSplit = part.indexOf("\r\n\r\n") !== -1 ? part.indexOf("\r\n\r\n") + 4 : part.indexOf("\n\n") + 2;
        htmlBody = part.slice(pSplit).trim();
      }
    }
  } else {
    // Single part email
    textBody = bodyContent.trim();
  }

  return {
    textBody: cleanMimeQuoting(textBody),
    htmlBody: htmlBody.trim(),
  };
}

function cleanMimeQuoting(str) {
  if (!str) return "";
  // Strip common quoted-printable artifacts
  return str.replace(/=\r?\n/g, "").replace(/=3D/g, "=").replace(/=20/g, " ");
}
