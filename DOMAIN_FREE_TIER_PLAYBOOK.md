# Flinza — 3-Domain Multi-Provider Free-Tier Stacking Playbook

> **The Zero-Cost Cold Outreach Engine**: How to stack free tiers across Brevo, Mailjet, Amazon SES, and Gmail to send **3,000+ emails/day (90,000+ emails/month) at $0 cost** with maximum deliverability.

---

## The Short Answer: YES, You Can Stack Free Tiers!

Here is how the math works and the exact rules for each provider:

| Provider | Free Limit Per Account | How to get 3x with 3 Domains | Total Free Output |
|---|---|---|---|
| **Brevo (Sendinblue)** | **300 emails / day** | Create **3 separate Brevo accounts** (1 per domain) | **900 emails / day** (27,000/mo) |
| **Mailjet** | **200 emails / day** (6,000/mo) | Create **3 separate Mailjet accounts** (1 per domain) | **600 emails / day** (18,000/mo) |
| **Gmail Send-As Relay** | **500 emails / day** | Use 3 master Gmails routing your 3 domains via Cloudflare | **1,500 emails / day** (45,000/mo) |
| **SMTP2GO** | **1,000 emails / month** | Create 3 SMTP2GO accounts | **3,000 emails / month** |
| **Amazon SES** | **50,000 / day** (Production) | Add **all 3 domains to 1 AWS account** ($0.10 per 1,000) | **Unlimited** ($3 for 30,000 emails) |

---

## 1. How to Stack 3 Brevo Accounts (900 Emails/Day for $0)

Brevo calculates the **300 emails/day limit per Brevo ACCOUNT**, not per domain:
- If you add 3 domains to *1 Brevo account*, they share the 300/day limit (100 each).
- **The Stacking Hack**:
  1. Create **Brevo Account 1** using `you+domain1@gmail.com` → Add & verify **Domain 1**.
  2. Create **Brevo Account 2** using `you+domain2@gmail.com` → Add & verify **Domain 2**.
  3. Create **Brevo Account 3** using `you+domain3@gmail.com` → Add & verify **Domain 3**.
  4. In your Flinza Command Center → **SMTP Vault**, save all 3 profiles:
     - Profile 1: `Brevo Domain 1` (`smtp-relay.brevo.com:587`, Key 1)
     - Profile 2: `Brevo Domain 2` (`smtp-relay.brevo.com:587`, Key 2)
     - Profile 3: `Brevo Domain 3` (`smtp-relay.brevo.com:587`, Key 3)
  5. **Total Capacity**: **300 × 3 = 900 emails every single day at $0!**

---

## 2. How to Stack 3 Mailjet Accounts (600 Emails/Day for $0)

Mailjet gives **6,000 emails/month (200 emails/day)** on their free plan:
1. Create 3 Mailjet accounts:
   - Account A → Verify Domain 1
   - Account B → Verify Domain 2
   - Account C → Verify Domain 3
2. Get API Key & Secret Key for each from **Account Settings → API Key Management**.
3. Save each into Flinza **SMTP Vault** under provider `mailjet`.
4. **Total Capacity**: **200 × 3 = 600 emails every single day at $0!**

---

## 3. How Amazon SES Works (The Heavyweight Alternative)

With Amazon SES, you **do not need 3 separate AWS accounts**:
1. **1 Single AWS Account** allows you to verify **unlimited domains** (Domain 1, Domain 2, Domain 3) inside SES.
2. When you request production access (takes 12–24h by telling AWS: *"We are an agency sending transactional updates and partnership outreach"*):
   - AWS gives you a quota of **50,000 emails / day**.
3. **Cost**: If sending outside EC2, AWS charges **$0.10 per 1,000 emails**.
   - Sending 10,000 emails costs **$1.00**.
   - Sending 30,000 emails costs **$3.00**.
   - It is essentially free for any agency scale.

---

## 4. ⚠️ CRITICAL: The Warmup Ramp-Up Rule

Even though you can technically send **1,500+ emails/day from Day 1**, **NEVER blast 300 emails on a fresh domain immediately**:
If a brand-new domain sends 300 emails in 24 hours without reputation, Spamhaus and Google spam filters will blacklist it permanently within 48 hours.

### Safe Warmup Schedule Per Domain:

| Week | Daily Volume Per Domain | Daily Volume Across All 3 Domains | Safe Provider |
|---|---|---|---|
| **Week 1 (Days 1–4)** | 10 – 15 emails | **30 – 45 emails** | Brevo / Gmail |
| **Week 1 (Days 5–7)** | 20 – 30 emails | **60 – 90 emails** | Brevo / Gmail |
| **Week 2** | 40 – 60 emails | **120 – 180 emails** | Brevo / Mailjet |
| **Week 3** | 75 – 100 emails | **225 – 300 emails** | Brevo / Mailjet / SES |
| **Week 4+ (Full Scale)** | 150 – 250 emails | **450 – 750+ emails** | All Multi-Provider Relay |

---

## Summary Checklist for Your 3 Domains

1. [ ] Set up **Cloudflare DNS** for all 3 domains with SPF, DKIM, and DMARC (`v=DMARC1; p=none; sp=none;`).
2. [ ] Create 3 Brevo accounts (1 per domain) and get 3 SMTP keys → Save to Flinza **SMTP Vault**.
3. [ ] Create 3 Mailjet accounts (1 per domain) and get API keys → Save to Flinza **SMTP Vault**.
4. [ ] Request production access on 1 Amazon SES account for backup high-volume burst.
5. [ ] Let Flinza's Warmup Engine ramp up sending automatically from 10 → 250 emails/day per domain.
