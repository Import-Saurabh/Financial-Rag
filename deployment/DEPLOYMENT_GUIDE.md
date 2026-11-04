# 🚀 Production Deployment Guide: Oracle Cloud (OCI Always Free)

This guide walks you through deploying **Financial-Rag** on an **Oracle Cloud Infrastructure (OCI) Always Free** Ampere A1 instance behind a **Caddy** reverse proxy with automatic SSL and WhatsApp Webhook integration.

---

## 🏗️ 1. Architecture Overview

```
                          ┌──────────────────────────────────────┐
                          │    Oracle Cloud (OCI Always Free)    │
[User on WhatsApp] ─────► │  VM.Standard.A1.Flex (2 OCPU, 12GB) │
       or                 │                                      │
[Web Browser Client] ───► │  [Port 443] Caddy (Auto HTTPS/TLS)   │
                          │        │                             │
                          │        ▼ reverse_proxy               │
                          │  [Port 5000] FastAPI Application     │
                          │    ├─ /webhook/whatsapp              │
                          │    ├─ /query & /v1/chat/completions  │
                          │    └─ Static Web Client (/)          │
                          └────────┬─────────────────────────────┘
                                   │
                   ┌───────────────┴──────────────┐
                   ▼                              ▼
     [Groq API (gpt-oss-120b)]      [Remote AWS Lambda Database]
     (Single-shot synthesis ~1.1s)  (Audited P&L, Balance Sheet, Ratios)
```

---

## ☁️ 2. Step 1: Provision the OCI Ampere A1 VM

1. Log into your **Oracle Cloud Console** (`cloud.oracle.com`).
2. Navigate to **Compute** $\rightarrow$ **Instances** $\rightarrow$ **Create Instance**.
3. Configure the instance:
   - **Name:** `financial-rag-prod`
   - **Image:** **Ubuntu 24.04 LTS** (or Ubuntu 22.04 LTS Minimal).
   - **Shape:** Click **Change Shape** $\rightarrow$ **Ampere (ARM Processor)** $\rightarrow$ **VM.Standard.A1.Flex**.
     - **OCPUs:** `2` (or up to `4` within Always Free limits).
     - **Memory (RAM):** `12 GB` (or up to `24 GB`).
   - **Networking:** Select your default Virtual Cloud Network (VCN) and ensure **Assign a public IPv4 address** is checked.
   - **SSH Keys:** Save the private key (`.key`) to your local machine and paste/upload the public key.
4. Click **Create** and wait 60 seconds for the instance status to turn **Running**. Note your **Public IP Address**.

---

## 🛡️ 3. Step 2: Open OCI VCN Ingress Rules (Ports 80 & 443)

By default, Oracle Cloud VCNs only permit SSH (port 22). You **must** add ingress rules for HTTP & HTTPS:

1. In the OCI Console, go to **Networking** $\rightarrow$ **Virtual Cloud Networks**.
2. Click your active VCN $\rightarrow$ Click **Security Lists** $\rightarrow$ Click **Default Security List for...**.
3. Under **Ingress Rules**, click **Add Ingress Rules**:
   - **Source CIDR:** `0.0.0.0/0`
   - **IP Protocol:** `TCP`
   - **Destination Port Range:** `80,443`
   - **Description:** `Allow HTTP and HTTPS for Caddy and WhatsApp Webhook`
4. Click **Add Ingress Rules**.

---

## 🌐 4. Step 3: Domain DNS Setup

WhatsApp Cloud API strictly requires a valid **HTTPS** domain on port 443 (IP addresses alone are rejected by Meta).

1. In your domain registrar (Cloudflare, Namecheap, GoDaddy, or DuckDNS):
   - Add an **A Record**:
     - **Name / Host:** `@` or `rag` (e.g. `rag.yourdomain.com`)
     - **Value / Target:** Your OCI VM Public IP (e.g. `140.238.xxx.xxx`)
     - **TTL:** Auto or 300 seconds
     - *(If using Cloudflare, set Proxy status to "DNS Only" / grey cloud initially for Caddy Let's Encrypt validation).*

---

## 💻 5. Step 4: Clone & Run Turnkey Setup on the VM

SSH into your new Oracle Cloud VM from your local terminal:

```bash
ssh -i /path/to/your-private-key.key ubuntu@<YOUR_OCI_PUBLIC_IP>
```

Once inside the VM, run:

```bash
# 1. Clone repository
git clone https://github.com/Import-Saurabh/Financial-Rag.git
cd Financial-Rag

# 2. Make the deployment script executable and run it
chmod +x deployment/setup_oci.sh
./deployment/setup_oci.sh
```

The script will automatically:
- Unblock Oracle host `iptables` and `ufw` on ports 80 & 443.
- Install `caddy`, `python3-venv`, and system dependencies.
- Build the `.venv` and install all packages from `Requirements.txt`.
- Configure `systemd` service `finrag.service` to auto-restart on reboot or crash.

---

## 🔑 6. Step 5: Configure Production Environment Variables

Edit `/home/ubuntu/Financial-Rag/.env`:

```bash
nano /home/ubuntu/Financial-Rag/.env
```

Ensure these core keys are filled:

```ini
# LLM Inference
GROQ_API_KEY=gsk_...

# Remote Financial DB API
FINRAG_API_BASE=https://zhwbvtkibdyhjy42gubo3qbsxq0pifuv.lambda-url.ap-south-1.on.aws

# WhatsApp Cloud API Webhook Secrets
WHATSAPP_VERIFY_TOKEN=finrag_verify_token_prod_2026
WHATSAPP_ACCESS_TOKEN=EAAG...
WHATSAPP_PHONE_NUMBER_ID=1092837465...
AUTHORIZED_WHATSAPP_NUMBER=919876543210
```

Save (`Ctrl+O`, `Enter`) and exit (`Ctrl+X`).

Restart the service to pick up the keys:

```bash
sudo systemctl restart finrag
sudo systemctl status finrag
```

---

## 🔒 7. Step 6: Configure Caddy for Instant HTTPS

Edit `/etc/caddy/Caddyfile`:

```bash
sudo nano /etc/caddy/Caddyfile
```

Replace `your-domain.com` with your real domain:

```caddy
rag.yourdomain.com {
    encode gzip zstd

    reverse_proxy 127.0.0.1:5000 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
```

Reload Caddy:

```bash
sudo systemctl reload caddy
```

Caddy will automatically obtain a trusted Let's Encrypt SSL certificate within 5–10 seconds!

Verify in your browser:
- Open `https://rag.yourdomain.com/` $\rightarrow$ You should see the Financial RAG Chat Interface!
- Open `https://rag.yourdomain.com/health` $\rightarrow$ Should return HTTP 200 JSON status.

---

## 📱 8. Step 7: Configure Meta WhatsApp Webhook

1. Go to the [Meta for Developers Portal](https://developers.facebook.com/).
2. Select your App $\rightarrow$ Go to **WhatsApp** $\rightarrow$ **Configuration**.
3. Under **Webhook**, click **Edit**:
   - **Callback URL:** `https://rag.yourdomain.com/webhook/whatsapp`
   - **Verify Token:** The exact value of `WHATSAPP_VERIFY_TOKEN` from your `.env` (e.g. `finrag_verify_token_prod_2026`).
4. Click **Verify and Save**. (FastAPI returns instant HTTP 200 within 20ms).
5. Click **Manage Webhook Fields** $\rightarrow$ Subscribe to **`messages`**.

---

## 🧪 9. Verification & Maintenance Commands

### Check Live Application Logs:
```bash
sudo journalctl -u finrag -f
```

### Check Caddy Web Traffic Logs:
```bash
sudo tail -f /var/log/caddy/finrag_access.log
```

### Restart Application:
```bash
sudo systemctl restart finrag
```

### Performance & Memory Check:
```bash
htop
```
*(On the 12GB Ampere VM, Financial-Rag uses ~800MB RAM, leaving >11GB headroom).*
