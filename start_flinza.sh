#!/usr/bin/env bash
# start_flinza.sh — Start Flinza CRM Dashboard
# Usage: bash start_flinza.sh
#
# The dashboard will be available at http://localhost:7880
# Login: rajdeep@flinzaconsuslting.com / Maa@2004

cd "$(dirname "$0")"

echo ""
echo "⚡ Starting Flinza CRM Dashboard..."
echo "   Dashboard: http://localhost:7880"
echo "   Network:   http://$(hostname -I | awk '{print $1}'):7880"
echo ""

# Kill any existing instance
pkill -f "python3 crm_server.py" 2>/dev/null
sleep 1

# Start CRM server
python3 crm_server.py
