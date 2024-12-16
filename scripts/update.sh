#!/bin/bash

echo "Updating CityBot2..."

# Stop the service
sudo systemctl stop citybot

# Activate virtual environment
source venv/bin/activate

# Pull latest changes if using git
if [ -d .git ]; then
    git pull
fi

# Update dependencies
pip install -r requirements.txt

# Restart the service
sudo systemctl start citybot

echo "Update complete. Checking service status..."
sudo systemctl status citybot