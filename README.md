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

* **Automated Uptime Tracking:** Periodically validates service status via HTTP requests.
* **Security Insights (Firewall Monitoring):** Post-processes system firewall logs to track and visualize blocked connection attempts, helping identify potential threats.
* **Traffic Analysis:** Monitors and summarizes incoming network traffic to provide a clear view of system load and usage patterns.
* **Clean Dashboard:** A minimalist UI to see at a glance service status, security metrics, and traffic data.
* **Lightweight Architecture:** Designed for high efficiency with minimal resource consumption.

## ⚙️ Installation & Setup

### Prerequisites
* Python 3.x
* pip (Python package manager)

### Steps

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/MDTrapaglia/status_page.git](https://github.com/MDTrapaglia/status_page.git)
   cd status_page
2. Install dependencies:
   pip install -r requirements.txt
3. Run the application: You can use the provided shell script:
chmod +x run.sh
./run.sh
Or run it directly with Python:

python app.py
