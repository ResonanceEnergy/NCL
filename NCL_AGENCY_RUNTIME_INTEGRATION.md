# NCL Agency Runtime v1 - Complete Integration

## Overview
The NCL Agency Runtime provides a complete local-first cognitive augmentation system that processes iPhone data streams, executes AI missions, and generates actionable insights. This runtime operationalizes the NUREALCORTEXLINK second brain architecture.

## System Architecture

### Core Components
- **Relay Server**: HTTP endpoint for iPhone event forwarding
- **Event Logger**: Append-only NDJSON storage with schema validation
- **Mission Runner**: AI agent execution engine for cognitive tasks
- **Report Generator**: Automated insight synthesis and presentation
- **Bootstrap System**: Local directory structure initialization

### Data Flow
1. **iPhone Events** → Shortcuts → HTTP POST → Relay Server
2. **Event Validation** → Schema compliance check → Quarantine or Accept
3. **Event Storage** → NDJSON append-only log → Daily rotation
4. **Mission Execution** → AI processing → Report generation
5. **Insight Delivery** → Markdown reports → User consumption

## Integration with NUREALCORTEXLINK

### Second Brain Architecture Mapping
- **Capture Agent**: Relay server and event ingestion
- **Organize Agent**: Schema validation and data structuring
- **Distill Agent**: Mission runner and pattern analysis
- **Express Agent**: Report generation and insight formatting
- **Transactive Memory**: Local NDJSON event logs
- **Digital Garden**: Mission reports and derived insights

### CODE Methodology Implementation
- **Capture**: iPhone sensors → Shortcuts → Relay → NDJSON logs
- **Organize**: Schema validation → Event categorization → Daily aggregation
- **Distill**: Mission processing → Pattern recognition → Insight generation
- **Express**: Report formatting → Action recommendations → User delivery

## Detailed Component Analysis

### 1. Relay Server (`runtime/relay_server.py`)
**Function**: HTTP endpoint for iPhone event forwarding
**Features**:
- Local network HTTP server (port 8787)
- JSON payload validation
- Schema compliance checking
- Quarantine for invalid events
- Append-only NDJSON logging

**Integration Points**:
- iOS Shortcuts POST requests
- Schema validation against `ncl.event.v1.json`
- Local filesystem storage
- Error handling and logging

### 2. Event Logger (`runtime/lib_ncl.py`)
**Function**: Append-only event storage system
**Features**:
- NDJSON format for efficient streaming
- Daily log rotation
- Schema validation
- Quarantine system for invalid events
- Minimal validation for required fields

**Data Structure**:
```json
{
  "schema_version": "ncl.event.v1",
  "event_id": "uuid",
  "event_type": "device.focus.changed",
  "occurred_at": "2026-02-22T10:00:00Z",
  "source": {"device": "iphone", "origin": "shortcuts"},
  "privacy": {"level": "P1", "raw_retention": "none"},
  "payload": {"from": "Personal", "to": "Work"}
}
```

### 3. Mission Runner (`runtime/mission_runner.py`)
**Function**: AI agent execution engine
**Features**:
- Mission queue processing
- Rules-based AI (v0 implementation)
- Report generation
- Daily brief automation
- Extensible agent framework

**Mission Types**:
- **Daily Brief**: Morning cognitive state assessment
- **Weekly Brief**: Pattern analysis and planning
- **Drift Investigation**: Behavioral change detection
- **Overload Investigation**: Cognitive load analysis

### 4. Bootstrap System (`scripts/bootstrap_windows.bat`)
**Function**: Local directory structure initialization
**Directory Structure**:
```
~/NCL/
├── data/
│   ├── event_log/     # Daily NDJSON files
│   ├── derived/       # Processed insights
│   ├── quarantine/    # Invalid events
│   └── indexes/       # Search indexes
├── agents/            # AI agent configurations
├── missions/          # Mission definitions
├── packs/             # Agent packages
├── policies/          # Governance rules
├── dist/              # Generated reports
└── audit/             # System logs
```

## Windows Adaptation

### Directory Structure
- Adapted bootstrap script for Windows paths
- Local user directory (`%USERPROFILE%\NCL`)
- Windows-compatible file operations

### Service Management
- No launchd equivalent (macOS service manager)
- Manual startup for relay server
- Scheduled task integration possible

### Network Configuration
- Localhost relay server (127.0.0.1:8787)
- LAN IP detection for iPhone connectivity
- Firewall considerations for local networking

## Execution Results

### Bootstrap Execution
```
[NCL] Bootstrapping local folders under C:\Users\<user>\NCL ...
[NCL] Done. Canonical root: C:\Users\<user>\NCL
[NCL] NOTE: This runtime is local-only. No cloud paths configured.
```

### Relay Server Startup
```
NCL Relay listening on http://0.0.0.0:8787/event
```

### Sample Event Processing
```json
{
  "ok": true,
  "stored": "C:\\Users\\<user>\\NCL\\data\\event_log\\2026-02-22.ndjson",
  "reason": "ok"
}
```

### Mission Execution
```
OK: wrote C:\Users\<user>\NCL\dist\reports\daily\2026-02-18.md
```

## Integration with Golden Task System

### Evaluation Framework
- **Event Processing**: Golden tasks can consume NDJSON event logs
- **Mission Validation**: AI outputs evaluated against golden standards
- **Performance Tracking**: Mission success rates measured
- **Continuous Improvement**: Golden task results inform agent training

### CODE Methodology Validation
- **Capture Tasks**: Event ingestion accuracy
- **Organize Tasks**: Data structuring quality
- **Distill Tasks**: Insight generation effectiveness
- **Express Tasks**: Communication clarity

## iOS Integration Workflow

### Shortcut Configuration
1. **Event Creation**: Build JSON payload with required fields
2. **Network Request**: POST to `http://<MAC_IP>:8787/event`
3. **Error Handling**: Offline fallback to local file storage
4. **Confirmation**: Success/failure feedback

### Event Types Supported
- `device.focus.changed`: Focus mode transitions
- `intent.capture.quicklog`: Energy/stress logging
- `notification.burst_event`: Notification patterns
- `screentime.session`: Usage session data
- Custom event types via schema extension

## Security & Privacy

### Local-First Design
- No cloud dependencies
- Data remains on local devices
- User-controlled retention policies
- Privacy-by-design architecture

### Data Protection
- Schema validation prevents malformed data
- Quarantine system for suspicious events
- Append-only logs prevent tampering
- User consent for all data collection

## Future Extensions

### Advanced Features
- **Real AI Agents**: Replace rules-based with ML models
- **Cross-Device Sync**: iPhone ↔ Mac data synchronization
- **Real-time Processing**: Streaming event analysis
- **Advanced Missions**: Complex multi-step cognitive tasks

### Integration Points
- **Golden Task Evaluation**: Automated agent performance testing
- **Knowledge Graph**: Event data integration with semantic web
- **Digital Garden**: Mission reports as garden content
- **Transactive Memory**: Multi-device memory synchronization

## Operational Status

### ✅ Successfully Executed Components
- Directory structure bootstrap
- Relay server startup and event processing
- NDJSON event logging
- Mission runner execution
- Daily brief report generation
- Schema validation and quarantine

### 🔧 Fixed Issues
- Syntax errors in Python scripts (unterminated strings)
- Windows path compatibility
- File encoding issues

### 📊 Performance Metrics
- **Event Processing**: Sub-second response times
- **Storage Efficiency**: NDJSON streaming format
- **Mission Execution**: Rules-based processing (v0)
- **Report Generation**: Markdown output formatting

This NCL Agency Runtime v1 provides a complete operational foundation for cognitive augmentation, successfully bridging iPhone data collection with AI processing and human insight delivery.