# 📊 Service Status Page

A lightweight, Python-powered monitoring tool designed to track and display the real-time availability of web services and infrastructure.

---

## 🚀 Overview

This project provides a clean and simple dashboard to monitor multiple URLs or services. It automatically checks for uptime and presents the results through a web interface, making it ideal for small teams or personal projects that need transparency on their system's health.

## 🛠️ Tech Stack

* **Backend:** [Python](https://www.python.org/) & [Flask](https://flask.palletsprojects.com/)
* **Frontend:** HTML5 & Jinja2 Templates
* **Automation:** Shell Scripting
* **Dependencies:** Managed via `requirements.txt`

## ✨ Key Features

* **Automated Health Checks:** Periodically validates service status via HTTP requests.
* **Clean Dashboard:** A minimalist UI to see at a glance which services are "Online" or "Offline".
* **Lightweight Architecture:** Minimal resource footprint, perfect for deploying on low-cost VPS or containers.
* **One-Step Execution:** Includes a `run.sh` script for quick environment setup and launch.

## ⚙️ Installation & Setup

### Prerequisites
* Python 3.x
* pip (Python package manager)

### Steps

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/MDTrapaglia/status_page.git](https://github.com/MDTrapaglia/status_page.git)
   cd status_page
