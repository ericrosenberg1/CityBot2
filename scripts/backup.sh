#!/bin/bash

# Create backup directory
BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p $BACKUP_DIR

# Backup database
cp data/citybot.db "$BACKUP_DIR/"

# Backup configurations
cp -r config/* "$BACKUP_DIR/config/"

# Backup logs
cp -r logs/* "$BACKUP_DIR/logs/"

# Create archive
tar -czf "$BACKUP_DIR.tar.gz" $BACKUP_DIR
rm -rf $BACKUP_DIR

echo "Backup created: $BACKUP_DIR.tar.gz"