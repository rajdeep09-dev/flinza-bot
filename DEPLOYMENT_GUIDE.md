# Flinza Works — Complete Deployment & SMTP Infrastructure Guide

This guide covers three battle-tested ways to deploy and send emails with Flinza:
1. **Option 1: 100% Free Production Architecture** (Free Cloudflare Email Routing Inbound + Free SMTP Outbound)
2. **Option 2: Cloudflare Native Outbound Sending** ($5/month Cloudflare Workers Paid plan — Zero SMTP, Zero Gmail)
3. **Option 3: Amazon SES High-Volume SMTP Setup** ($0.10 per 1,000 emails or 62,000 free/mo on AWS EC2)

---

## 🟢 OPTION 1: 100% Free Production Architecture

Run high-converting B2B outreach with **zero monthly infrastructure costs**.

```
[Outbound: Free Gmail / Brevo / SES] ──> [Prospect Inbox]
                                              │
                                              ▼ (Prospect Replies)
[Flinza Webhook / Unibox] <── [Free Cloudflare Worker] <── [Cloudflare Email Routing]
```

### Step 1: Set Up 100% Free Inbound Email Routing
Cloudflare provides free inbound email routing for any domain on Cloudflare with no message limits.

1. In the [Cloudflare Dashboard](https://dash.cloudflare.com/), select your domain (e.g., `magicfitpartners.com`).
2. Navigate to **Email Routing → Enable Email Routing**. Cloudflare will automatically add the necessary MX and TXT records to your DNS.
3. Deploy the Flinza Inbound Worker:
   - Go to **Workers & Pages → Create Application → Create Worker**.
   - Name it `flinza-inbound-router`.
   - Click **Deploy**, then click **Edit code**.
   - Copy the entire contents of [`cloudflare_email_worker.js`](file:///c:/Users/Nabir%20Hossain/OneDrive/antigravity%20tele/flinza/cloudflare_email_worker.js) and paste it into the Worker editor.
   - Go to Worker **Settings → Variables**:
     - Add `FLINZA_WEBHOOK_URL`: `https://your-flinza-domain.com/api/webhooks/inbound` (or your ngrok / Cloudflare Tunnel URL during local testing)
     - Add `FLINZA_WEBHOOK_SECRET`: `flinza_cf_inbound_secret_2026`
     - *(Optional)* Add `FORWARD_TO`: `your-personal-gmail@gmail.com` to keep a copy in your personal inbox.
   - Click **Save and deploy**.
4. Route Inbound Emails to Your Worker:
   - Go back to your domain → **Email Routing → Routing Rules**.
   - Click **Create rule** or edit **Catch-all rule**.
   - Action: **Send to a Worker** → Select `flinza-inbound-router`.
   - Now, any prospect replying to `alex@magicfitpartners.com`, `sales@...`, or any alias will instantly be pushed into Flinza's Unibox with AI intent classification and instant Telegram alerts!

### Step 2: Set Up Free Outbound Sending
Choose either:
- **Free Gmail Inboxes (Up to 500 emails/day per account)**:
  - Enable 2-Step Verification in Google Account Settings.
  - Generate an **App Password** (`Security → 2-Step Verification → App passwords`).
  - Add to Flinza via Web Studio (`http://localhost:8000`) or Telegram bot (`/addaccount`).
- **Free Brevo / SendGrid (300 emails/day free)**:
  - Create free account on Brevo (formerly Sendinblue).
  - Get SMTP credentials (`smtp-relay.brevo.com:587`).
  - Add to Flinza as an SMTP account.

---

## ⚡ OPTION 2: Cloudflare Native Outbound Sending ($5/Month Workers Paid Plan)

*Built on the architecture from [0xdps/emailflare](https://github.com/0xdps/emailflare).*
Cloudflare now offers native **Cloudflare Email Sending** via REST API on the **Workers Paid Plan ($5/month)**.

### Why Use This?
- **Zero SMTP Configuration**: No SMTP usernames, passwords, or port headaches.
- **Pure REST API**: Emails are dispatched directly via HTTPS POST requests from Cloudflare's edge network.
- **Custom Domain Authority**: Sends natively from `sales@yourdomain.com` matching your Cloudflare zone records.

### Step 1: Enable Cloudflare Workers Paid & Email Sending
1. Log in to [Cloudflare](https://dash.cloudflare.com/).
2. Navigate to **Workers & Pages → Plans** and upgrade to the **Workers Paid Plan ($5/mo)**.
3. In your Cloudflare Dashboard, go to **Email Routing / Sending** and verify that your sending domain is active.

### Step 2: Create a Cloudflare API Token
1. Go to **My Profile → API Tokens → Create Token**.
2. Click **Create Custom Token**:
   - Token name: `Flinza Email Sending Token`
   - Permissions:
     - `Account` | `Email Sending` | `Edit`
     - `Zone` | `Email Routing` | `Edit`
     - `Zone` | `DNS` | `Read`
   - Account Resources: `Include` → `All Accounts`
   - Zone Resources: `Include` → `All Zones`
3. Click **Continue to summary** → **Create Token**. Copy the token string immediately.

### Step 3: Get Your Account ID
1. In Cloudflare, select any domain on your account.
2. In the right sidebar under **Overview**, copy your **Account ID**.

### Step 4: Configure Flinza
1. In `flinza/.env`:
   ```env
   CF_ACCOUNT_ID=your_cloudflare_account_id_here
   CF_API_TOKEN=your_cloudflare_api_token_here
   ```
2. In Flinza Web Studio (`http://localhost:8000`):
   - Click **Mailbox Fleet → ➕ Add Mailbox / Provider**.
   - Click the **Cloudflare API ($5/mo)** tab.
   - Enter your from email: `alex@magicfitpartners.com`.
   - Set daily limit (e.g. `100`).
   - Click **Add Cloudflare Sender**.
3. Flinza will now dispatch cold emails through `https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send`!

---

## 🚀 OPTION 3: Amazon SES High-Volume SMTP Setup

Amazon SES (Simple Email Service) is the **industry gold standard** for bulk B2B cold emailing:
- **Price**: $0.10 for every 1,000 emails sent ($1 sends 10,000 emails!).
- **Free Tier**: **62,000 emails/month free** when running from AWS EC2.
- **Deliverability**: Top-tier sender reputation and dedicated IP options.

### Step 1: Create Amazon SES Domain Identity
1. Log in to the [AWS Management Console](https://console.aws.amazon.com/ses).
2. Select your closest AWS Region (e.g., `us-east-1` N. Virginia or `eu-west-1` Ireland).
3. In the left menu, click **Identities → Create identity**.
4. Select **Domain** and enter your domain name (e.g., `magicfitpartners.com`).
5. Check **Easy DKIM** (RSA 2048-bit).
6. Click **Create identity**.

### Step 2: Add DNS Records to Cloudflare
AWS SES will display:
- **3 CNAME Records for DKIM**:
  ```
  Name:  xxxx._domainkey.yourdomain.com
  Value: xxxx.dkim.amazonses.com
  Proxy status: DNS ONLY (Grey Cloud, NOT Proxied)
  ```
- **1 TXT Record for SPF**:
  ```
  Name:  @ (or yourdomain.com)
  Value: v=spf1 include:amazonses.com ~all
  ```
- **1 TXT Record for DMARC**:
  ```
  Name:  _dmarc
  Value: v=DMARC1; p=none; rua=mailto:dmarc-reports@yourdomain.com;
  ```
Add these in **Cloudflare Dashboard → DNS Records**. Make sure DKIM CNAMEs are set to **DNS Only** (unproxied). Within 5 minutes, AWS SES will show `Domain Status: Verified` 🟢.

### Step 3: Request Production Access (Move out of Sandbox)
*New SES accounts start in Sandbox mode (can only send to verified emails).*
1. In the AWS SES Console, look at the top banner: click **Request production access**.
2. Mail type: **Transactional / Outreach**.
3. Use case description:
   > *"We are a B2B Social Media Marketing Agency (Flinza Works) reaching out to prospective business partners and clients with personalized 1-on-1 marketing propositions. All recipients have opt-out links, bounces are automatically suppressed, and emails comply with CAN-SPAM regulations."*
4. AWS typically approves production access within 4 to 12 hours, giving you a starting quota of **50,000 emails/day**!

### Step 4: Generate SES SMTP Credentials
1. In the AWS SES Console, click **SMTP settings** in the left sidebar.
2. Note your **SMTP endpoint**: `email-smtp.us-east-1.amazonaws.com` (Port 587).
3. Click **Create SMTP credentials**.
4. AWS will create an IAM user. Click **Create user** and download the credentials:
   - **SMTP Username**: `AKIA...`
   - **SMTP Password**: `B...` (Note: This is an SES SMTP password, not your AWS root password).

### Step 5: Add Amazon SES to Flinza
#### Via Web Studio:
1. Open [http://localhost:8000](http://localhost:8000).
2. Go to **Mailbox Fleet → ➕ Add Mailbox / Provider**.
3. Click the **Amazon SES / SMTP** tab.
4. Enter:
   - Sender Email: `outreach@magicfitpartners.com`
   - SES Username: `AKIA...`
   - SES Password: `Your_SES_Password`
   - Host: `email-smtp.us-east-1.amazonaws.com` (Port: `587`)
   - Daily limit: `250`
5. Click **Add Amazon SES Mailbox**.

#### Or via `.env`:
```env
AWS_SES_REGION=us-east-1
AWS_SES_SMTP_HOST=email-smtp.us-east-1.amazonaws.com
AWS_SES_SMTP_PORT=587
AWS_SES_SMTP_USER=AKIA...
AWS_SES_SMTP_PASS=Your_SES_Password
```

---

## 🛠️ Summary Matrix: Which Provider to Use?

| Requirement | Best Choice | Cost |
|---|---|---|
| **Zero Cost (Testing & Small Campaigns)** | Free Cloudflare Inbound Worker + Free Gmail Accounts | **$0.00 / month** |
| **No SMTP / Pure API Outbound** | Cloudflare Native Email Sending REST API | **$5.00 / month** (Workers Paid) |
| **High-Volume Agency Cold Outreach (10k - 100k+ emails)** | Amazon SES with Cloudflare DNS | **$0.10 / 1,000 emails** |
| **Inbound Reply Tracking with AI** | Cloudflare Email Routing Worker (`cloudflare_email_worker.js`) | **100% Free** (100k req/day) |
