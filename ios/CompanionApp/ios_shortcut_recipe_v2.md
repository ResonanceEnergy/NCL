# iOS Shortcut for NCL Event Relay

## Overview
This shortcut enables iPhone users to send cognitive state data to the NCL Agency Runtime relay server running on a Mac/Windows machine. It captures focus mode changes, energy levels, and other cognitive metrics.

## Shortcut Configuration

### Shortcut Name
`NCL Event Relay`

### Actions Required

#### 1. Initialize Variables
```
Set Variable: EventType → "device.focus.changed"
Set Variable: SchemaVersion → "ncl.event.v1"
Set Variable: RelayHost → "http://192.168.1.100:8787"  # Replace with your Mac/Windows IP
```

#### 2. Get Current Focus Mode
```
Find Focus: Get Details
Set Variable: FromFocus → Focus Name
Set Variable: ToFocus → Focus Name  # This should be the new focus mode
```

#### 3. Build Event Payload
```
Dictionary:
  schema_version: SchemaVersion
  event_id: Shortcut Input → UUID
  event_type: EventType
  occurred_at: Current Date → Formatted Date (ISO 8601)
  source: Dictionary
    device: "iphone"
    origin: "shortcuts"
    version: "1.0"
  privacy: Dictionary
    level: "P1"
    raw_retention: "none"
  payload: Dictionary
    from: FromFocus
    to: ToFocus
    transition_type: "manual"
```

#### 4. Send to Relay Server
```
Get Contents of URL:
  URL: RelayHost + "/event"
  Method: POST
  Headers:
    Content-Type: application/json
  Request Body: EventPayload (JSON)
  Timeout: 10 seconds
```

#### 5. Handle Response
```
Get Details of URL Response: Status Code
If Status Code = 200:
  Show Notification: "✓ NCL Event Sent"
Else:
  Show Notification: "✗ NCL Relay Failed"
  Set Variable: ErrorDetails → Response Body
  Log Error to Console
```

## Alternative Event Types

### Energy/Stress Logging
```
Event Type: "intent.capture.quicklog"
Payload:
  energy_level: Ask for Input (1-10 scale)
  stress_level: Ask for Input (1-10 scale)
  context: Ask for Input ("work", "personal", "exercise", etc.)
```

### Notification Burst
```
Event Type: "notification.burst_event"
Payload:
  burst_count: Number of notifications in last 5 minutes
  burst_duration: Duration of burst
  interruption_level: "high" | "medium" | "low"
```

### Screen Time Session
```
Event Type: "screentime.session"
Payload:
  total_time: Screen time in minutes
  category_breakdown: Dictionary of app categories
  most_used_app: Top app name
```

## Network Configuration

### Finding Your Mac/Windows IP
1. On Mac: System Settings → Network → Wi-Fi → IP Address
2. On Windows: Settings → Network & Internet → Wi-Fi → Hardware properties
3. Update the `RelayHost` variable in the shortcut

### Firewall Settings
- **Mac**: System Settings → Network → Firewall → Turn off for private networks
- **Windows**: Windows Defender Firewall → Allow app through firewall → Python

## Testing the Shortcut

### 1. Start Relay Server
```bash
# On Mac
cd ~/NCL/ZIPZ/NCL_AGENCY_Runtime_Mac_v1_LocalOnly/ncl_gbx_one_drop/runtime
python relay_server.py

# On Windows
cd %USERPROFILE%\NCL\ZIPZ\NCL_AGENCY_Runtime_Mac_v1_LocalOnly\ncl_gbx_one_drop\runtime
python relay_server.py
```

### 2. Run Shortcut on iPhone
- Open Shortcuts app
- Run the NCL Event Relay shortcut
- Check relay server console for event receipt
- Verify event appears in NDJSON log file

### 3. Verify Event Storage
Check the daily log file:
```
~/NCL/data/event_log/YYYY-MM-DD.ndjson
```

## Advanced Features

### Offline Fallback
Add logic to store events locally when network unavailable:
```
If URL request fails:
  Append to File: Local event storage
  Set Variable: PendingSync → true
```

### Batch Processing
Collect multiple events before sending:
```
Add to List: Event queue
If List count > 5:
  Send batch to relay
  Clear list
```

### Location Context
Add location data for context-aware processing:
```
Get Current Location
Add to payload:
  location: Dictionary
    latitude: Location Latitude
    longitude: Location Longitude
    accuracy: Location Accuracy
```

## Troubleshooting

### Common Issues

#### "Connection Failed"
- Check IP address in shortcut
- Ensure relay server is running
- Verify firewall settings
- Confirm same Wi-Fi network

#### "Invalid Event"
- Check JSON payload structure
- Verify schema compliance
- Review required fields

#### "Server Not Responding"
- Check relay server logs
- Verify port 8787 availability
- Restart relay server

### Debug Mode
Add debug output to shortcut:
```
Show Notification: EventPayload (as JSON)
Log to Console: Full response details
```

## Integration with Daily Workflow

### Automation Suggestions
1. **Morning Routine**: Energy level logging
2. **Focus Changes**: Automatic focus mode tracking
3. **Evening Review**: Daily cognitive state summary
4. **Notification Management**: Burst detection and logging

### Custom Triggers
- **Time-based**: Daily energy check at 9 AM
- **Location-based**: Work/home context switching
- **App-based**: Screen time threshold alerts
- **Focus-based**: Automatic focus mode change logging

This shortcut provides the bridge between iPhone cognitive data collection and the NCL Agency Runtime processing pipeline, enabling the complete second brain workflow.