#!/usr/bin/env bash
# ==============================================================================
# setup_oci.sh — Turnkey Deployment Script for Oracle Cloud Infrastructure (OCI)
# Target OS: Ubuntu 22.04 / 24.04 LTS (Ampere A1 ARM64 or x86_64)
# ==============================================================================

set -euo pipefail

echo "=========================================================="
echo "🚀 Starting Financial RAG Deployment on Oracle Cloud (OCI)"
echo "=========================================================="

APP_DIR="/home/ubuntu/Financial-Rag"
USER="ubuntu"

# 1. Update OS packages
echo "📦 Updating OS packages..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl debian-keyring debian-archive-keyring apt-transport-https \
    python3-pip python3-venv git iptables-persistent net-tools

# 2. Configure Host Firewall (CRITICAL FOR ORACLE CLOUD)
# Oracle Cloud Ubuntu instances have pre-configured iptables rules that DROP 
# incoming traffic on ports 80 & 443 by default even if VCN Security List allows it.
echo "🛡️ Configuring Oracle Cloud OS Firewall for Ports 80 & 443..."
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT || sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT || sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save

if command -v ufw >/dev/null 2>&1; then
    sudo ufw allow 22/tcp || true
    sudo ufw allow 80/tcp || true
    sudo ufw allow 443/tcp || true
    sudo ufw --force enable || true
fi

# 3. Install Caddy (Automated HTTPS Reverse Proxy)
echo "🔒 Installing Caddy Server..."
if ! command -v caddy >/dev/null 2>&1; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
    sudo apt update
    sudo apt install -y caddy
fi

# 4. Set up Python Virtual Environment
echo "🐍 Setting up Python Virtual Environment in ${APP_DIR}..."
cd "${APP_DIR}"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r Requirements.txt

# 5. Check Environment Configuration
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "⚠️  No .env file found! Copying .env.example to .env..."
        cp .env.example .env
        echo "❗ Remember to edit /home/ubuntu/Financial-Rag/.env with your actual GROQ_API_KEY and WhatsApp tokens!"
    fi
fi

# 6. Configure Systemd Service
echo "⚙️ Configuring Systemd Service Units..."
sudo cp "${APP_DIR}/deployment/finrag.service" /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable finrag.service
sudo systemctl restart finrag.service

# 7. Configure Caddyfile
if [ -f "${APP_DIR}/deployment/Caddyfile" ]; then
    echo "📋 Copying Caddyfile to /etc/caddy/Caddyfile..."
    echo "❗ Please edit /etc/caddy/Caddyfile to replace 'your-domain.com' with your actual domain!"
    sudo cp "${APP_DIR}/deployment/Caddyfile" /etc/caddy/Caddyfile
    sudo systemctl restart caddy
fi

echo "=========================================================="
echo "✅ Deployment setup complete!"
echo "Status check:"
sudo systemctl status finrag.service --no-pager -l
echo "=========================================================="
echo "Next Steps:"
echo "1. Set your domain DNS 'A' record to point to this VM's Public IP."
echo "2. Edit /etc/caddy/Caddyfile with your domain and run: sudo systemctl reload caddy"
echo "3. Update /home/ubuntu/Financial-Rag/.env with your production API keys."
echo "4. In Meta for Developers, configure your webhook callback URL:"
echo "   https://<your-domain>/webhook/whatsapp"
echo "=========================================================="
