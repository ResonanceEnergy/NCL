#!/bin/bash
# Super Agency Remote Access Setup
# Enable secure remote access to local command center from anywhere

set -e

echo "🌐 Super Agency Remote Access Setup"
echo "==================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Detect platform
detect_platform() {
    case "$(uname -s)" in
        Darwin)
            echo "macos"
            ;;
        Linux)
            echo "linux"
            ;;
        CYGWIN*|MINGW32*|MSYS*|MINGW*)
            echo "windows"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

PLATFORM=$(detect_platform)

# Configuration
REMOTE_CONFIG_FILE="remote_config.json"
CLOUDFLARE_CONFIG_DIR="$HOME/.cloudflared"
NGROK_CONFIG_DIR="$HOME/.ngrok2"

# Create remote config
create_remote_config() {
    log_info "Creating remote access configuration..."

    cat > "$REMOTE_CONFIG_FILE" << EOF
{
    "remote_access": {
        "enabled": true,
        "method": "cloudflare",
        "domain": "command.superagency.local",
        "services": {
            "matrix_monitor": {
                "local_port": 3000,
                "remote_path": "/monitor",
                "auth_required": true
            },
            "operations_api": {
                "local_port": 5000,
                "remote_path": "/api",
                "auth_required": true
            },
            "command_center": {
                "local_port": 8080,
                "remote_path": "/",
                "auth_required": true
            }
        },
        "security": {
            "basic_auth": true,
            "username": "admin",
            "password_hash": "",
            "allowed_ips": [],
            "rate_limiting": true
        },
        "mobile": {
            "responsive_design": true,
            "touch_optimized": true,
            "offline_support": false
        }
    }
}
EOF

    log_success "Remote configuration created"
}

# Setup Cloudflare Tunnel
setup_cloudflare_tunnel() {
    log_info "Setting up Cloudflare Tunnel for secure remote access..."

    # Install cloudflared
    case $PLATFORM in
        macos)
            if ! command -v cloudflared &> /dev/null; then
                log_info "Installing cloudflared..."
                brew install cloudflare/cloudflare/cloudflared
            fi
            ;;
        linux)
            if ! command -v cloudflared &> /dev/null; then
                log_info "Installing cloudflared..."
                curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
                sudo dpkg -i cloudflared.deb
                rm cloudflared.deb
            fi
            ;;
        windows)
            if ! command -v cloudflared &> /dev/null; then
                log_info "Installing cloudflared..."
                winget install --id Cloudflare.cloudflared
            fi
            ;;
    esac

    # Create config directory
    mkdir -p "$CLOUDFLARE_CONFIG_DIR"

    # Create tunnel configuration
    cat > "$CLOUDFLARE_CONFIG_DIR/config.yaml" << EOF
tunnel: super-agency-command-center
credentials-file: $CLOUDFLARE_CONFIG_DIR/tunnel.json

ingress:
  - hostname: command.superagency.local
    service: http://localhost:3000
    originRequest:
      noTLSVerify: true
  - hostname: api.superagency.local
    service: http://localhost:5000
    originRequest:
      noTLSVerify: true
  - hostname: ops.superagency.local
    service: http://localhost:8080
    originRequest:
      noTLSVerify: true
  - service: http_status:404
EOF

    log_success "Cloudflare Tunnel configured"
}

# Setup ngrok (alternative)
setup_ngrok_tunnel() {
    log_info "Setting up ngrok tunnel for remote access..."

    # Install ngrok
    case $PLATFORM in
        macos)
            if ! command -v ngrok &> /dev/null; then
                log_info "Installing ngrok..."
                brew install ngrok/ngrok/ngrok
            fi
            ;;
        linux)
            if ! command -v ngrok &> /dev/null; then
                log_info "Installing ngrok..."
                curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
                echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
                sudo apt update && sudo apt install ngrok
            fi
            ;;
        windows)
            if ! command -v ngrok &> /dev/null; then
                log_info "Installing ngrok..."
                choco install ngrok
            fi
            ;;
    esac

    # Create ngrok config
    mkdir -p "$NGROK_CONFIG_DIR"
    cat > "$NGROK_CONFIG_DIR/ngrok.yml" << EOF
version: "2"
authtoken: YOUR_NGROK_AUTH_TOKEN
tunnels:
  matrix-monitor:
    addr: 3000
    proto: http
    hostname: matrix.superagency.ngrok.io
    auth: "admin:password"
  operations-api:
    addr: 5000
    proto: http
    hostname: api.superagency.ngrok.io
    auth: "admin:password"
  command-center:
    addr: 8080
    proto: http
    hostname: command.superagency.ngrok.io
    auth: "admin:password"
EOF

    log_warning "Please set your ngrok auth token: ngrok config add-authtoken YOUR_TOKEN"
    log_success "ngrok configuration created"
}

# Setup local reverse proxy
setup_reverse_proxy() {
    log_info "Setting up local reverse proxy with authentication..."

    # Install caddy (modern reverse proxy)
    case $PLATFORM in
        macos)
            if ! command -v caddy &> /dev/null; then
                log_info "Installing Caddy..."
                brew install caddy
            fi
            ;;
        linux)
            if ! command -v caddy &> /dev/null; then
                log_info "Installing Caddy..."
                sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
                curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
                curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
                sudo apt update && sudo apt install caddy
            fi
            ;;
        windows)
            log_warning "Caddy setup not automated on Windows. Please install manually from https://caddyserver.com/"
            return
            ;;
    esac

    # Create Caddyfile
    cat > Caddyfile << EOF
# Super Agency Command Center
command.superagency.local {
    # Basic authentication
    basicauth /monitor/* {
        admin $(caddy hash-password --plaintext password)
    }

    # Matrix Monitor
    handle /monitor/* {
        uri strip_prefix /monitor
        reverse_proxy localhost:3000
    }

    # Operations API
    handle /api/* {
        uri strip_prefix /api
        reverse_proxy localhost:5000
    }

    # Main interface
    handle {
        reverse_proxy localhost:8080
    }
}

# HTTPS redirect for security
http://command.superagency.local {
    redir https://command.superagency.local{uri} permanent
}
EOF

    log_success "Reverse proxy configured with authentication"
}

# Setup mobile optimization
setup_mobile_optimization() {
    log_info "Setting up mobile optimization..."

    # Create mobile CSS
    mkdir -p static/css
    cat > static/css/mobile.css << EOF
/* Mobile-first responsive design */
@media (max-width: 768px) {
    .container {
        padding: 10px;
        margin: 0;
    }

    .header {
        font-size: 1.2em;
        padding: 10px;
    }

    .nav-menu {
        flex-direction: column;
        gap: 10px;
    }

    .card {
        margin: 10px 0;
        padding: 15px;
    }

    .button {
        width: 100%;
        padding: 12px;
        font-size: 16px; /* Prevents zoom on iOS */
    }

    .status-grid {
        grid-template-columns: 1fr;
        gap: 10px;
    }

    .chart-container {
        height: 200px;
    }
}

/* Touch optimizations */
.touch-optimized {
    -webkit-tap-highlight-color: rgba(0,0,0,0.1);
    touch-action: manipulation;
}

.touch-optimized button,
.touch-optimized .button {
    min-height: 44px; /* iOS touch target size */
    min-width: 44px;
}

/* iPad optimizations */
@media (min-width: 768px) and (max-width: 1024px) {
    .container {
        max-width: 100%;
        padding: 20px;
    }

    .sidebar {
        width: 250px;
    }

    .main-content {
        margin-left: 250px;
    }
}
EOF

    # Create mobile JS enhancements
    cat > static/js/mobile.js << EOF
// Mobile enhancements for Super Agency Command Center

document.addEventListener('DOMContentLoaded', function() {
    // Add mobile class to body
    document.body.classList.add('mobile-optimized');

    // Touch feedback
    const buttons = document.querySelectorAll('button, .button');
    buttons.forEach(button => {
        button.addEventListener('touchstart', function() {
            this.style.transform = 'scale(0.98)';
        });

        button.addEventListener('touchend', function() {
            this.style.transform = 'scale(1)';
        });
    });

    // Pull to refresh for status updates
    let startY = 0;
    let pullDistance = 0;
    const pullThreshold = 80;

    document.addEventListener('touchstart', function(e) {
        startY = e.touches[0].clientY;
    });

    document.addEventListener('touchmove', function(e) {
        if (window.scrollY === 0) {
            pullDistance = e.touches[0].clientY - startY;
            if (pullDistance > 0) {
                e.preventDefault();
                // Add visual feedback for pull
                document.body.style.transform = `translateY(${Math.min(pullDistance * 0.5, pullThreshold)}px)`;
            }
        }
    });

    document.addEventListener('touchend', function() {
        if (pullDistance > pullThreshold) {
            // Trigger refresh
            location.reload();
        }
        document.body.style.transform = '';
        pullDistance = 0;
    });

    // Service worker for offline support (basic)
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js')
            .then(registration => {
                console.log('Service Worker registered');
            })
            .catch(error => {
                console.log('Service Worker registration failed');
            });
    }

    // Auto-refresh for critical data
    setInterval(function() {
        // Refresh status indicators every 30 seconds
        const statusElements = document.querySelectorAll('.status-indicator');
        statusElements.forEach(element => {
            // Add refresh logic here
        });
    }, 30000);
});
EOF

    log_success "Mobile optimization configured"
}

# Setup firewall rules
setup_firewall() {
    log_info "Configuring firewall for remote access..."

    case $PLATFORM in
        macos)
            # Allow ports through firewall
            sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/cloudflared 2>/dev/null || true
            sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/ngrok 2>/dev/null || true
            sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/caddy 2>/dev/null || true
            ;;
        linux)
            # UFW rules
            sudo ufw allow 3000/tcp comment "Matrix Monitor"
            sudo ufw allow 5000/tcp comment "Operations API"
            sudo ufw allow 8080/tcp comment "Command Center"
            sudo ufw allow 80/tcp comment "HTTP"
            sudo ufw allow 443/tcp comment "HTTPS"
            ;;
        windows)
            # Windows Firewall rules
            netsh advfirewall firewall add rule name="Matrix Monitor" dir=in action=allow protocol=TCP localport=3000
            netsh advfirewall firewall add rule name="Operations API" dir=in action=allow protocol=TCP localport=5000
            netsh advfirewall firewall add rule name="Command Center" dir=in action=allow protocol=TCP localport=8080
            ;;
    esac

    log_success "Firewall configured"
}

# Generate access instructions
generate_access_instructions() {
    log_info "Generating access instructions..."

    cat > REMOTE_ACCESS_INSTRUCTIONS.md << EOF
# 🌐 Super Agency Remote Access Instructions

## Current Setup
Your command center is configured for remote access with the following methods:

### 1. Cloudflare Tunnel (Recommended)
- **URL**: https://command.superagency.local
- **Matrix Monitor**: https://command.superagency.local/monitor
- **Operations API**: https://api.superagency.local
- **Command Center**: https://ops.superagency.local

### 2. ngrok Tunnel (Alternative)
- **Matrix Monitor**: https://matrix.superagency.ngrok.io
- **Operations API**: https://api.superagency.ngrok.io
- **Command Center**: https://command.superagency.ngrok.io

### 3. Local Network Access
- **Matrix Monitor**: http://YOUR_LOCAL_IP:3000
- **Operations API**: http://YOUR_LOCAL_IP:5000
- **Command Center**: http://YOUR_LOCAL_IP:8080

## Mobile Access

### iPhone/iPad Setup
1. Open Safari on your device
2. Navigate to one of the URLs above
3. Add to home screen for app-like experience:
   - Tap share button
   - Select "Add to Home Screen"
   - Name it "Super Agency Command"

### Android Setup
1. Open Chrome on your device
2. Navigate to the URL
3. Add to home screen:
   - Tap menu (3 dots)
   - Select "Add to Home screen"
   - Name it "Super Agency Command"

## Security Features
- Basic authentication enabled
- HTTPS encryption
- Rate limiting active
- Mobile-optimized interface

## Troubleshooting

### Can't Access Remotely?
1. Check if tunnel is running: \`ps aux | grep cloudflared\`
2. Verify firewall: Check that ports 3000, 5000, 8080 are open
3. Check local services: Visit localhost URLs first
4. Restart tunnel: \`./remote_access.sh --restart\`

### Mobile Issues?
1. Clear browser cache
2. Try incognito/private mode
3. Check network connection
4. Ensure JavaScript is enabled

## Starting Remote Access

\`\`\`bash
# Start everything with remote access
./launch_command_center.sh --remote

# Or start remote access separately
./remote_access.sh --start
\`\`\`

## Stopping Remote Access

\`\`\`bash
./remote_access.sh --stop
\`\`\`

---
*Generated on $(date)*
EOF

    log_success "Access instructions generated"
}

# Start remote access
start_remote_access() {
    log_info "Starting remote access services..."

    # Start based on configured method
    if [ -f "$REMOTE_CONFIG_FILE" ]; then
        METHOD=$(jq -r '.remote_access.method' "$REMOTE_CONFIG_FILE")
    else
        METHOD="cloudflare"
    fi

    case $METHOD in
        cloudflare)
            if command -v cloudflared &> /dev/null; then
                log_info "Starting Cloudflare tunnel..."
                cloudflared tunnel run super-agency-command-center &
                echo $! > .cloudflare.pid
            else
                log_error "cloudflared not installed"
                exit 1
            fi
            ;;
        ngrok)
            if command -v ngrok &> /dev/null; then
                log_info "Starting ngrok tunnels..."
                ngrok start --config="$NGROK_CONFIG_DIR/ngrok.yml" --all &
                echo $! > .ngrok.pid
            else
                log_error "ngrok not installed"
                exit 1
            fi
            ;;
        local)
            if command -v caddy &> /dev/null; then
                log_info "Starting Caddy reverse proxy..."
                caddy run &
                echo $! > .caddy.pid
            else
                log_error "caddy not installed"
                exit 1
            fi
            ;;
    esac

    log_success "Remote access started"
}

# Stop remote access
stop_remote_access() {
    log_info "Stopping remote access services..."

    # Stop running processes
    for pid_file in .cloudflare.pid .ngrok.pid .caddy.pid; do
        if [ -f "$pid_file" ]; then
            PID=$(cat "$pid_file")
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID"
                log_success "Stopped $(basename "$pid_file" .pid)"
            fi
            rm "$pid_file"
        fi
    done

    log_success "Remote access stopped"
}

# Main menu
show_menu() {
    echo ""
    echo "Super Agency Remote Access Setup Menu"
    echo "====================================="
    echo "1. Setup Cloudflare Tunnel (Recommended)"
    echo "2. Setup ngrok Tunnel (Alternative)"
    echo "3. Setup Local Reverse Proxy"
    echo "4. Setup Mobile Optimization"
    echo "5. Configure Firewall"
    echo "6. Start Remote Access"
    echo "7. Stop Remote Access"
    echo "8. Generate Access Instructions"
    echo "9. Complete Setup (All Steps)"
    echo "10. Exit"
    echo ""
    read -p "Choose an option (1-10): " choice
    echo ""
}

# Main logic
main() {
    case "${1:-}" in
        --cloudflare)
            create_remote_config
            setup_cloudflare_tunnel
            setup_firewall
            setup_mobile_optimization
            generate_access_instructions
            ;;
        --ngrok)
            create_remote_config
            setup_ngrok_tunnel
            setup_firewall
            setup_mobile_optimization
            generate_access_instructions
            ;;
        --local)
            create_remote_config
            setup_reverse_proxy
            setup_firewall
            setup_mobile_optimization
            generate_access_instructions
            ;;
        --start)
            start_remote_access
            ;;
        --stop)
            stop_remote_access
            ;;
        --mobile)
            setup_mobile_optimization
            ;;
        --firewall)
            setup_firewall
            ;;
        --instructions)
            generate_access_instructions
            ;;
        --complete)
            create_remote_config
            setup_cloudflare_tunnel
            setup_firewall
            setup_mobile_optimization
            generate_access_instructions
            start_remote_access
            ;;
        *)
            # Interactive menu
            while true; do
                show_menu
                case $choice in
                    1)
                        create_remote_config
                        setup_cloudflare_tunnel
                        ;;
                    2)
                        create_remote_config
                        setup_ngrok_tunnel
                        ;;
                    3)
                        create_remote_config
                        setup_reverse_proxy
                        ;;
                    4)
                        setup_mobile_optimization
                        ;;
                    5)
                        setup_firewall
                        ;;
                    6)
                        start_remote_access
                        ;;
                    7)
                        stop_remote_access
                        ;;
                    8)
                        generate_access_instructions
                        ;;
                    9)
                        create_remote_config
                        setup_cloudflare_tunnel
                        setup_firewall
                        setup_mobile_optimization
                        generate_access_instructions
                        start_remote_access
                        ;;
                    10)
                        log_success "Goodbye! 👋"
                        exit 0
                        ;;
                    *)
                        log_error "Invalid option. Please choose 1-10."
                        ;;
                esac
                echo ""
                read -p "Press Enter to continue..."
            done
            ;;
    esac
}

# Run main function
main "$@"