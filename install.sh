#!/bin/bash

echo "Installing CityBot2..."

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install system dependencies
sudo apt-get update
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    libatlas-base-dev \
    gfortran \
    libgeos-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    libcairo2-dev \
    pkg-config \
    python3-cartopy \
    cutycapt

# Install Python dependencies
pip install -r requirements.txt

# Create necessary directories
mkdir -p {logs,data,cache/weather_maps,cache/maps,config}

# Copy configuration files
cp config/credentials.env.example config/credentials.env
cp config/social_config.json.example config/social_config.json

# Set up service
sudo cp citybot.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "Installation complete. Please follow these steps:"
echo ""
echo "1. Edit configuration files:"
echo "   nano config/credentials.env"
echo "   nano config/social_config.json"
echo ""
echo "2. Start the service:"
echo "   sudo systemctl start citybot"
echo ""
echo "3. Enable service at boot:"
echo "   sudo systemctl enable citybot"
echo ""
echo "4. Check service status:"
echo "   sudo systemctl status citybot"
echo ""
echo "5. View logs:"
echo "   tail -f logs/citybot.log"