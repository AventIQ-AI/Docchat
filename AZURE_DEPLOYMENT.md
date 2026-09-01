# Azure VM Deployment Guide for Ollama Folder RAG REST API

This guide walks you through deploying the **Ollama Folder RAG REST API** system onto an Azure Virtual Machine (VM) and exposing HTTP APIs for external applications or frontends.

---

## 1. Architecture Overview

```
[ External Client / Web Frontend ]
               │
               ▼  (HTTP / HTTPS Port 8000 / 443)
┌─────────────────────────────────────────────────────────────┐
│                       AZURE VIRTUAL MACHINE                 │
│                                                             │
│  ┌─────────────────┐   ┌──────────────────┐   ┌──────────┐  │
│  │   FastAPI App   │──►│ PostgreSQL       │   │  Ollama  │  │
│  │ (Port 8000/docs)│   │ (pgvector DB)    │   │  Engine  │  │
│  └─────────────────┘   └──────────────────┘   └──────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Recommended Azure VM Specifications

| Workload | VM Size | vCPU | RAM | Disk | GPU |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CPU Only (Default)** | Standard_D4s_v5 | 4 | 16 GB | 64 GB SSD | None |
| **GPU Accelerated** | Standard_NC6s_v3 | 6 | 112 GB | 128 GB SSD | NVIDIA V100 |

---

## 3. Azure VM Provisioning Steps

### Step A: Create Azure VM via Azure Portal or CLI

Using **Azure CLI**:

```bash
# 1. Create Resource Group
az group create --name rag-chatbot-rg --location eastus

# 2. Create VM (Ubuntu 22.04 LTS)
az vm create \
  --resource-group rag-chatbot-rg \
  --name rag-api-vm \
  --image Ubuntu2204 \
  --admin-username azureuser \
  --generate-ssh-keys \
  --size Standard_D4s_v5 \
  --public-ip-sku Standard
```

### Step B: Open Inbound Ports in Azure NSG

Open port **8000** (REST API & Interactive Docs) and port **22** (SSH):

```bash
az vm open-port --resource-group rag-chatbot-rg --name rag-api-vm --port 8000 --priority 1010
```

---

## 4. Deploying to the Azure VM

### Step A: Connect to VM via SSH

```bash
ssh azureuser@<YOUR_AZURE_VM_PUBLIC_IP>
```

### Step B: Install Docker & Docker Compose

Run on the Azure VM terminal:

```bash
# Update & install prerequisites
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release git

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Verify Docker & Docker Compose
docker compose version
```

### Step C: Clone Repository & Configure Environment

```bash
# Clone repository
git clone <YOUR_GIT_REPOSITORY_URL> ollama-folder-rag
cd ollama-folder-rag

# Create environment file
cp .env.example .env
```

If you want to secure the API with an API key, edit `.env`:

```env
API_KEY=your_secret_api_key_here
CORS_ORIGINS=*
```

### Step D: Launch the Application Stack

```bash
docker compose up -d
```

This single command starts:
1. **PostgreSQL 16 + pgvector** database.
2. **Ollama Service** (downloads `qwen3:4b` and `qwen3-embedding:0.6b` automatically).
3. **FastAPI Web Application** on port `8000`.

To view startup logs:

```bash
docker compose logs -f
```

---

## 5. API Reference & Usage

Once deployed, access the interactive OpenAPI documentation at:

```
http://<YOUR_AZURE_VM_PUBLIC_IP>:8000/docs
```

### Key Endpoint Examples

#### 1. System Health Check

```http
GET http://<YOUR_AZURE_VM_PUBLIC_IP>:8000/api/health
```

#### 2. Query RAG Chatbot

```http
POST http://<YOUR_AZURE_VM_PUBLIC_IP>:8000/api/query
Content-Type: application/json

{
  "question": "What is the policy for annual leave?",
  "history": [],
  "top_k": 5
}
```

**Response**:

```json
{
  "question": "What is the policy for annual leave?",
  "answer": "Employees are entitled to 24 days of annual leave per year [S1].",
  "sources": [
    {
      "chunk_id": 1,
      "file_name": "Employee-Handbook.pdf",
      "source_path": "documents/Employee-Handbook.pdf",
      "page_number": 14,
      "similarity": 0.9124,
      "text": "Employees are entitled to 24 days of annual leave..."
    }
  ]
}
```

#### 3. Upload Document(s) via API

```bash
curl -X POST "http://<YOUR_AZURE_VM_PUBLIC_IP>:8000/api/documents/upload" \
  -F "files=@/path/to/local/policy.pdf"
```

#### 4. List Indexed Documents

```http
GET http://<YOUR_AZURE_VM_PUBLIC_IP>:8000/api/documents
```

#### 5. Delete an Indexed Document

```http
DELETE http://<YOUR_AZURE_VM_PUBLIC_IP>:8000/api/documents/1
```

---

## 6. (Optional) Enabling GPU Acceleration on Azure

If using an Azure GPU VM (e.g. `Standard_NC6s_v3`):

1. Install NVIDIA GPU Drivers & Container Toolkit on VM:
   ```bash
   sudo apt-get install -y nvidia-container-toolkit
   sudo systemctl restart docker
   ```
2. Uncomment the `deploy.resources.reservations.devices` block in `docker-compose.yml` under the `ollama` service.
3. Restart: `docker compose up -d`.
