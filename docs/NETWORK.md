# Network & Privacy Guide

ArkhamMirror is designed as a **local-first** platform. Once fully set up, the application can run completely offline. However, initial setup and certain features require network access. This document explains exactly what network calls are made and how to disable them.

---

## TL;DR - Quick Offline Setup

For users who need to run in a fully air-gapped environment:

1. **Complete initial setup on a networked machine** (downloads models, dependencies)
2. **Disable telemetry** (see sections below)
3. **Transfer the entire ArkhamMirror folder** to your air-gapped machine
4. **Run offline** - no further network access required

---

## Network Activity Overview

### First-Run Downloads (Required)

These downloads happen **once** during initial setup and are **required** for the application to function:

| Source | What Downloads | Size | Purpose |
|--------|---------------|------|---------|
| `huggingface.co` | BGE-M3 embedding model | ~2.2 GB | Semantic search (or MiniLM ~80 MB for minimal install) |
| `huggingface.co` | spaCy en_core_web_sm | ~12 MB | Entity recognition (NER) |
| `bcebos.com` / `paddlepaddle.org.cn` | PaddleOCR models | ~150 MB | OCR text extraction |
| `pypi.org` | Python packages | ~500 MB | Application dependencies |
| `registry.npmjs.org` | Node.js packages | ~200 MB | Frontend dependencies |
| `docker.io` | Container images | ~1 GB | PostgreSQL, Qdrant, Redis |

**Note:** PaddleOCR models are hosted on Baidu's cloud infrastructure. If you have concerns about downloading from Chinese servers, you can pre-download models from alternative mirrors or use the LM Studio + Qwen-VL OCR option instead.

### Runtime Telemetry (Disabled by Default)

ArkhamMirror ships with telemetry **disabled by default** to protect user privacy:

| Service | Domain | Purpose | Default | Override |
|---------|--------|---------|---------|----------|
| Qdrant Telemetry | `telemetry.qdrant.io` | Vector DB usage stats | **Disabled** | Set `QDRANT_TELEMETRY_DISABLED=false` to enable |
| Reflex Analytics | `posthog.com` | Framework usage analytics | Varies | Set `REFLEX_ANALYTICS_ENABLED=false` to disable |

**Note:** Reflex (the web framework) may include PostHog analytics in some versions. If you observe connections to `posthog.com`, set `REFLEX_ANALYTICS_ENABLED=false` in your environment.

### What Was Fixed (Security Review)

A security review identified the following issues that have been addressed:

| Issue | Status | Fix Applied |
|-------|--------|-------------|
| Google Fonts CDN | **Fixed** | Inter font is now self-hosted in `/assets/fonts/` |
| Qdrant telemetry default | **Fixed** | Now defaults to disabled in docker-compose.yml |
| ModelScope connectivity check | **Fixed** | Set `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` in ocr_worker.py |
| Cloudflare 1.1.1.1 connectivity check | **Fixed** | Set `REFLEX_HTTP_CLIENT_BIND_ADDRESS=127.0.0.1` (see below) |
| LAN exposure (backend_host) | **Fixed** | Set `backend_host="127.0.0.1"` in rxconfig.py (see below) |
| PaddleOCR Chinese servers | Documented | One-time download; use Qwen-VL as alternative |
| HuggingFace downloads | Documented | One-time download; can pre-download for air-gap |

### Cloudflare 1.1.1.1 - Root Cause & Fix

**Root Cause:** Reflex (the web framework) performs IPv4/IPv6 connectivity detection by making HTTP HEAD requests to Cloudflare's public DNS resolver IPs (`1.1.1.1` for IPv4, `2606:4700:4700::1111` for IPv6). This happens in `reflex/utils/net.py` on the first network request (e.g., version check, template download).

**Fix Applied:** The setup scripts (`setup.bat`, `setup.sh`) and `ai_installer.py` now set `REFLEX_HTTP_CLIENT_BIND_ADDRESS=127.0.0.1` before any Reflex imports, which skips the auto-detection.

**For pure IPv6 networks:** Set `REFLEX_HTTP_CLIENT_BIND_ADDRESS=::` instead in your `.env` file.

**Note:** `REFLEX_HTTP_CLIENT_BIND_ADDRESS` controls *outbound* HTTP client requests, not server listening. Using `127.0.0.1` is a belt-and-suspenders safety measure for consistency with our localhost-only security posture — while `0.0.0.0` would also work here (since it's for outbound, not inbound), we use `127.0.0.1` everywhere for peace of mind.

### LAN Exposure - Root Cause & Fix

**Root Cause:** Reflex defaults `backend_host` to `0.0.0.0`, which means the backend API listens on *all network interfaces*. If you're on a shared network (coffee shop WiFi, office LAN), anyone on that network could potentially access your ArkhamMirror instance by typing your local IP address (e.g., `192.168.1.5:8000`).

**Fix Applied:** We explicitly set `backend_host="127.0.0.1"` in `app/rxconfig.py`, ensuring the backend *only* listens on localhost. This aligns with ArkhamMirror's air-gapped security model.

**For "Team Mode" (LAN access):** If you intentionally want to share your instance with other devices on your network, you can override this by setting `BACKEND_HOST=0.0.0.0` in your `.env` file. Only do this on trusted networks.

If you observe connections to other unexpected domains, please open an issue with network capture details.

### Never Contacted

ArkhamMirror **never** sends your documents, queries, or analysis results to any external server. All document processing, AI inference (via LM Studio), and search happens 100% locally.

---

## Telemetry Configuration

### Default: Telemetry Disabled

As of the latest version, **Qdrant telemetry is disabled by default** in `docker-compose.yml`. No action is required.

For Reflex/PostHog analytics (if present in your Reflex version), add to your `.env` file:

```bash
# Disable Reflex/PostHog analytics
REFLEX_ANALYTICS_ENABLED=false
```

### Re-enabling Telemetry (Optional)

If you want to help improve these projects by sharing anonymous usage data:

```bash
# Enable Qdrant telemetry
QDRANT_TELEMETRY_DISABLED=false

# Enable Reflex analytics
REFLEX_ANALYTICS_ENABLED=true
```

### Firewall Rules (Maximum Security)

For high-security environments, block outbound connections at the firewall level:

```bash
# Linux/iptables example - block telemetry domains
iptables -A OUTPUT -d posthog.com -j DROP
iptables -A OUTPUT -d telemetry.qdrant.io -j DROP
```

---

## Air-Gapped Installation

For environments with no internet access, follow this procedure:

### On a Networked Machine

1. **Clone and set up ArkhamMirror normally:**

   ```bash
   git clone https://github.com/mantisfury/ArkhamMirror.git
   cd ArkhamMirror
   ```

2. **Install all dependencies:**

   ```bash
   cd app
   python -m venv venv
   source venv/bin/activate  # or .\venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

3. **Pre-download models:**

   ```bash
   # This triggers model downloads
   python -c "from FlagEmbedding import BGEM3FlagModel; BGEM3FlagModel('BAAI/bge-m3')"
   python -c "import spacy; spacy.cli.download('en_core_web_sm')"
   python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='en')"
   ```

4. **Pull Docker images:**

   ```bash
   docker pull postgres:15
   docker pull qdrant/qdrant:latest
   docker pull redis:7
   docker pull busybox:latest
   ```

5. **Save Docker images for transfer:**

   ```bash
   docker save postgres:15 qdrant/qdrant:latest redis:7 busybox:latest | gzip > arkham-images.tar.gz
   ```

6. **Create the transfer package:**
   - Copy the entire `ArkhamMirror/` folder
   - Include `arkham-images.tar.gz`
   - Include any downloaded models from `~/.cache/huggingface/` and `~/.paddleocr/`

### On the Air-Gapped Machine

1. **Load Docker images:**

   ```bash
   gunzip -c arkham-images.tar.gz | docker load
   ```

2. **Copy model caches to correct locations:**
   - HuggingFace models: `~/.cache/huggingface/`
   - PaddleOCR models: `~/.paddleocr/`
   - spaCy models: installed in the venv

3. **Disable telemetry** (see above)

4. **Start the application:**

   ```bash
   cd docker && docker compose up -d
   cd ../app && reflex run
   ```

---

## Verifying Offline Operation

To confirm no network calls are being made:

### Linux/Mac

```bash
# Monitor network connections while running
sudo lsof -i -P | grep -E "python|node|postgres|qdrant|redis"
```

### Windows

```powershell
# In PowerShell as Administrator
netstat -b | Select-String -Pattern "python|node|postgres|qdrant|redis"
```

### Using Wireshark

1. Start Wireshark on your network interface
2. Filter: `not (ip.addr == 127.0.0.1)`
3. Run ArkhamMirror and observe - there should be no external traffic after initial setup

---

## FAQ

**Q: Why does PaddleOCR download from Chinese servers?**
A: PaddleOCR is developed by Baidu and their model hosting is on Baidu Cloud (bcebos.com). This is a one-time download. If this is a concern, you can use the Qwen-VL OCR option via LM Studio instead, which downloads from HuggingFace.

**Q: Can I use ArkhamMirror without any internet at all?**
A: Yes, but you must complete the initial setup (downloading models and dependencies) on a machine with internet first, then transfer to your air-gapped environment.

**Q: Is my data ever sent anywhere?**
A: No. Your documents, search queries, entities, and analysis results are stored exclusively in the local `DataSilo/` folder. The telemetry mentioned above only tracks anonymized usage statistics of the framework itself, not your data.

**Q: What about LM Studio?**
A: LM Studio runs completely locally. The initial model download happens within LM Studio itself (from HuggingFace), and after that, all inference is local.

---

## Summary

| Activity | When | Can Disable? |
|----------|------|--------------|
| Model downloads | First run only | No (required) |
| Package installs | Setup only | No (required) |
| Reflex analytics | Runtime | Yes |
| Qdrant telemetry | Runtime | Yes |
| Document processing | Runtime | N/A (always local) |
| AI inference | Runtime | N/A (always local) |

Once models are downloaded and telemetry is disabled, ArkhamMirror operates in a fully air-gapped manner.
