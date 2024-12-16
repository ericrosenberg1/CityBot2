#!/bin/bash

# Set default number of lines
LINES=${1:-50}

# Display recent logs
echo "Recent bot activity:"
tail -n $LINES logs/citybot.log