#!/bin/bash
# STF Digital Twin - Simulation Runner Script
# This script starts all simulation services in separate terminals

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  STF Digital Twin - Simulation Runner  ${NC}"
echo -e "${BLUE}========================================${NC}"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    exit 1
fi

# Check if required packages are installed
echo -e "${YELLOW}Checking Python dependencies...${NC}"
pip3 install -q -r requirements.txt 2>/dev/null || {
    echo -e "${RED}Failed to install Python dependencies${NC}"
    echo -e "${YELLOW}Try running: pip3 install -r requirements.txt${NC}"
    exit 1
}

# Function to start a service
start_service() {
    local name=$1
    local command=$2
    echo -e "${GREEN}Starting $name...${NC}"
    
    if command -v gnome-terminal &> /dev/null; then
        gnome-terminal --title="$name" -- bash -c "$command; exec bash"
    elif command -v xterm &> /dev/null; then
        xterm -title "$name" -e "$command" &
    elif command -v tmux &> /dev/null; then
        tmux new-session -d -s "$name" "$command"
        echo -e "${YELLOW}Started $name in tmux session. Attach with: tmux attach -t $name${NC}"
    else
        echo -e "${YELLOW}No terminal emulator found. Starting $name in background...${NC}"
        nohup $command > "${name}.log" 2>&1 &
        echo -e "${YELLOW}Logs: ${name}.log${NC}"
    fi
}

# Parse command line arguments
case "${1:-all}" in
    "docker")
        echo -e "${YELLOW}Starting Docker infrastructure...${NC}"
        docker-compose up -d
        echo -e "${GREEN}Docker services started!${NC}"
        echo -e "  MySQL:     localhost:3306"
        echo -e "  MQTT:      localhost:1883"
        echo -e "  Adminer:   http://localhost:8080"
        ;;
    
    "hardware")
        echo -e "${YELLOW}Starting Mock Hardware...${NC}"
        python3 -m stf_warehouse.hardware.mock_hbw
        ;;
    
    "controller")
        echo -e "${YELLOW}Starting Controller...${NC}"
        python3 -m stf_warehouse.controller.main_controller
        ;;
    
    "all")
        echo -e "${YELLOW}Starting all simulation services...${NC}"
        
        # Start Docker if available
        if command -v docker-compose &> /dev/null; then
            echo -e "${YELLOW}Starting Docker infrastructure...${NC}"
            docker-compose up -d 2>/dev/null || echo -e "${YELLOW}Docker not available, skipping...${NC}"
        fi
        
        # Start services
        start_service "STF-MockHardware" "cd $SCRIPT_DIR && python3 -m stf_warehouse.hardware.mock_hbw"
        sleep 2
        start_service "STF-Controller" "cd $SCRIPT_DIR && python3 -m stf_warehouse.controller.main_controller"
        
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  All services started!                 ${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo ""
        echo -e "Services running:"
        echo -e "  ${BLUE}Mock Hardware${NC}: Simulating HBW robot at 10Hz"
        echo -e "  ${BLUE}Controller${NC}:    Processing commands and safety interlocks"
        echo ""
        echo -e "To stop all services:"
        echo -e "  ${YELLOW}pkill -f 'stf_warehouse'${NC}"
        echo -e "  ${YELLOW}docker-compose down${NC}"
        ;;
    
    "stop")
        echo -e "${YELLOW}Stopping all services...${NC}"
        pkill -f 'stf_warehouse' 2>/dev/null || true
        docker-compose down 2>/dev/null || true
        echo -e "${GREEN}All services stopped${NC}"
        ;;
    
    *)
        echo "Usage: $0 {all|docker|hardware|controller|stop}"
        echo ""
        echo "Commands:"
        echo "  all        - Start all simulation services"
        echo "  docker     - Start only Docker infrastructure (MySQL, MQTT)"
        echo "  hardware   - Start only Mock Hardware simulation"
        echo "  controller - Start only Main Controller"
        echo "  stop       - Stop all services"
        exit 1
        ;;
esac
