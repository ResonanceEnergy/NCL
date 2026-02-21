#!/bin/bash
# Super Agency Memory Doctrine Logs Backup System
# Saves current state, doctrine updates, and log backups

set -e

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="backups/memory_doctrine_logs_$TIMESTAMP"
LOG_FILE="backups/backup_log_$TIMESTAMP.txt"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log_info() {
    log "INFO: $1"
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    log "SUCCESS: $1"
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    log "WARNING: $1"
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    log "ERROR: $1"
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create backup directory
create_backup_dir() {
    log_info "Creating backup directory: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"
    mkdir -p "$BACKUP_DIR/doctrine"
    mkdir -p "$BACKUP_DIR/memory"
    mkdir -p "$BACKUP_DIR/logs"
    mkdir -p "$BACKUP_DIR/config"
    mkdir -p "$BACKUP_DIR/state"
    log_success "Backup directories created"
}

# Save current memory state
save_memory() {
    log_info "Saving current memory state..."

    # Session memory capture
    if [ -f "SESSION_MEMORY_CAPTURE.md" ]; then
        cp "SESSION_MEMORY_CAPTURE.md" "$BACKUP_DIR/memory/session_memory_$TIMESTAMP.md"
        log_success "Session memory captured"
    fi

    # Inner council intelligence
    if [ -f "inner_council_intelligence.log" ]; then
        cp "inner_council_intelligence.log" "$BACKUP_DIR/memory/inner_council_intelligence_$TIMESTAMP.log"
        log_success "Inner council intelligence saved"
    fi

    # YouTube intelligence data
    if [ -d "youtube_intelligence_data" ]; then
        cp -r "youtube_intelligence_data" "$BACKUP_DIR/memory/youtube_intelligence_data_$TIMESTAMP"
        log_success "YouTube intelligence data saved"
    fi

    # Current operations state
    if [ -f "operations_command_interface.py" ]; then
        # Capture current running processes
        ps aux | grep -E "(python|node)" | grep -v grep > "$BACKUP_DIR/state/processes_$TIMESTAMP.txt" 2>/dev/null || true
        log_success "Current process state captured"
    fi

    log_success "Memory state saved"
}

# Save doctrine files
save_doctrine() {
    log_info "Saving doctrine files..."

    # Core doctrine files
    DOCTRINE_FILES=(
        "DOCTRINE_NCL_SECOND_BRAIN.md"
        "DOCTRINE_COUNCIL_52.md"
        "SUPER_AGENCY_DOCTRINE_MEMORY.md"
        "NORTH_STAR.md"
        "ROADMAP.md"
    )

    for file in "${DOCTRINE_FILES[@]}"; do
        if [ -f "$file" ]; then
            cp "$file" "$BACKUP_DIR/doctrine/$(basename "$file" .md)_$TIMESTAMP.md"
            log_success "Doctrine saved: $file"
        else
            log_warning "Doctrine file not found: $file"
        fi
    done

    # NCL Second Brain doctrine
    if [ -d "ncl_second_brain" ]; then
        cp -r "ncl_second_brain/contracts" "$BACKUP_DIR/doctrine/ncl_contracts_$TIMESTAMP" 2>/dev/null || true
        cp -r "ncl_second_brain/engine" "$BACKUP_DIR/doctrine/ncl_engine_$TIMESTAMP" 2>/dev/null || true
        log_success "NCL Second Brain doctrine saved"
    fi

    log_success "All doctrine files saved"
}

# Backup logs
backup_logs() {
    log_info "Backing up log files..."

    # Main logs directory
    if [ -d "logs" ]; then
        cp -r "logs" "$BACKUP_DIR/logs/main_logs_$TIMESTAMP"
        log_success "Main logs backed up"
    fi

    # NCC logs
    if [ -d "ncc_logs" ]; then
        cp -r "ncc_logs" "$BACKUP_DIR/logs/ncc_logs_$TIMESTAMP"
        log_success "NCC logs backed up"
    fi

    # Oversight logs
    if [ -d "oversight_logs" ]; then
        cp -r "oversight_logs" "$BACKUP_DIR/logs/oversight_logs_$TIMESTAMP"
        log_success "Oversight logs backed up"
    fi

    # Inner council logs
    if [ -f "inner_council_intelligence.log" ]; then
        cp "inner_council_intelligence.log" "$BACKUP_DIR/logs/inner_council_$TIMESTAMP.log"
        log_success "Inner council logs backed up"
    fi

    # YouTube intelligence logs
    if [ -f "youtube_intelligence.log" ]; then
        cp "youtube_intelligence.log" "$BACKUP_DIR/logs/youtube_intelligence_$TIMESTAMP.log"
        log_success "YouTube intelligence logs backed up"
    fi

    # Reports directory
    if [ -d "reports" ]; then
        cp -r "reports" "$BACKUP_DIR/logs/reports_$TIMESTAMP"
        log_success "Reports backed up"
    fi

    # Daily reports
    if [ -d "reports/daily" ]; then
        cp -r "reports/daily" "$BACKUP_DIR/logs/daily_reports_$TIMESTAMP"
        log_success "Daily reports backed up"
    fi

    log_success "All logs backed up"
}

# Save configuration
save_config() {
    log_info "Saving configuration files..."

    # Config directory
    if [ -d "config" ]; then
        cp -r "config" "$BACKUP_DIR/config/main_config_$TIMESTAMP"
        log_success "Main config saved"
    fi

    # Inner council config
    if [ -f "inner_council_config.json" ]; then
        cp "inner_council_config.json" "$BACKUP_DIR/config/inner_council_config_$TIMESTAMP.json"
        log_success "Inner council config saved"
    fi

    # YouTube intelligence config
    if [ -f "youtube_intelligence_config.json" ]; then
        cp "youtube_intelligence_config.json" "$BACKUP_DIR/config/youtube_config_$TIMESTAMP.json"
        log_success "YouTube config saved"
    fi

    # Portfolio files
    if [ -f "portfolio.json" ]; then
        cp "portfolio.json" "$BACKUP_DIR/config/portfolio_$TIMESTAMP.json"
        log_success "Portfolio config saved"
    fi

    if [ -f "portfolio.yaml" ]; then
        cp "portfolio.yaml" "$BACKUP_DIR/config/portfolio_$TIMESTAMP.yaml"
        log_success "Portfolio YAML saved"
    fi

    log_success "Configuration saved"
}

# Save current state
save_state() {
    log_info "Saving current system state..."

    # Git status
    if [ -d ".git" ]; then
        git status --porcelain > "$BACKUP_DIR/state/git_status_$TIMESTAMP.txt" 2>/dev/null || true
        git log --oneline -10 > "$BACKUP_DIR/state/git_log_$TIMESTAMP.txt" 2>/dev/null || true
        log_success "Git state saved"
    fi

    # Running processes related to Super Agency
    ps aux | grep -E "(super.agency|operations|matrix.monitor|ncl|doctrine)" | grep -v grep > "$BACKUP_DIR/state/super_agency_processes_$TIMESTAMP.txt" 2>/dev/null || true

    # Disk usage
    df -h > "$BACKUP_DIR/state/disk_usage_$TIMESTAMP.txt" 2>/dev/null || true

    # Memory usage
    free -h > "$BACKUP_DIR/state/memory_usage_$TIMESTAMP.txt" 2>/dev/null || true

    log_success "System state saved"
}

# Create backup manifest
create_manifest() {
    log_info "Creating backup manifest..."

    MANIFEST="$BACKUP_DIR/BACKUP_MANIFEST_$TIMESTAMP.txt"

    echo "Super Agency Memory Doctrine Logs Backup" > "$MANIFEST"
    echo "Timestamp: $TIMESTAMP" >> "$MANIFEST"
    echo "Date: $(date)" >> "$MANIFEST"
    echo "==========================================" >> "$MANIFEST"
    echo "" >> "$MANIFEST"

    echo "BACKUP CONTENTS:" >> "$MANIFEST"
    echo "===============" >> "$MANIFEST"
    find "$BACKUP_DIR" -type f | sort >> "$MANIFEST"

    echo "" >> "$MANIFEST"
    echo "BACKUP SUMMARY:" >> "$MANIFEST"
    echo "==============" >> "$MANIFEST"
    echo "Total files: $(find "$BACKUP_DIR" -type f | wc -l)" >> "$MANIFEST"
    echo "Total size: $(du -sh "$BACKUP_DIR" | cut -f1)" >> "$MANIFEST"

    log_success "Backup manifest created: $MANIFEST"
}

# Compress backup
compress_backup() {
    log_info "Compressing backup..."

    ARCHIVE_NAME="super_agency_backup_$TIMESTAMP.tar.gz"
    tar -czf "$ARCHIVE_NAME" -C "backups" "memory_doctrine_logs_$TIMESTAMP"

    if [ -f "$ARCHIVE_NAME" ]; then
        log_success "Backup compressed: $ARCHIVE_NAME"
        log_info "Compressed size: $(du -sh "$ARCHIVE_NAME" | cut -f1)"

        # Clean up uncompressed backup
        rm -rf "$BACKUP_DIR"
        log_success "Uncompressed backup cleaned up"
    else
        log_error "Compression failed"
    fi
}

# Main execution
main() {
    echo "🧠 Super Agency Memory Doctrine Logs Backup"
    echo "=========================================="
    echo "Timestamp: $TIMESTAMP"
    echo ""

    log_info "Starting comprehensive backup operation..."

    create_backup_dir
    save_memory
    save_doctrine
    backup_logs
    save_config
    save_state
    create_manifest

    echo ""
    log_success "Backup completed successfully!"
    echo "📁 Backup location: $BACKUP_DIR"
    echo "📋 Log file: $LOG_FILE"

    # Ask about compression
    echo ""
    read -p "Compress backup? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        compress_backup
    fi

    echo ""
    log_success "Memory, doctrine, and logs backup complete!"
    echo "🔄 System ready for continued operations"
}

# Run main function
main "$@"