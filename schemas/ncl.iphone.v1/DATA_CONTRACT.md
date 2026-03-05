# NCL iPhone Data Contract v1.0

## Overview
This document defines the data collection contracts for NCL iPhone integration, specifying permissions, ingestion methods, retention tiers, privacy levels, and derived features for each data stream.

## Core Principles
- **Consent-First**: All data collection requires explicit user permission
- **Privacy-by-Design**: Minimal data collection with maximum privacy protection
- **Local-First**: Data processing occurs on-device when possible
- **Auditability**: All data operations are logged and auditable

## Permission Categories

### System Permissions
- **Screen Time**: Device activity monitoring
- **Health Data**: HealthKit integration (optional)
- **Location**: Geographic context (optional)
- **Notifications**: Notification monitoring
- **Device State**: Battery, focus modes, orientation

### Data Contract Structure
Each event type includes:
- **Permission Requirements**: iOS permissions needed
- **Ingestion Method**: How data enters the system
- **Retention Tier**: How long data is kept
- **Privacy Level**: Data sensitivity classification
- **Derived Features**: Computed insights from raw data

## Event Type Contracts

### Screen Time Events
#### `screentime.total.json`
- **Permission**: Screen Time access
- **Ingestion**: HealthKit API polling
- **Retention**: Short-term (7 days)
- **Privacy**: Metadata-only
- **Derived**: Usage trends, attention load baseline

#### `screentime.by_category.json`
- **Permission**: Screen Time access
- **Ingestion**: HealthKit API polling
- **Retention**: Short-term (7 days)
- **Privacy**: Metadata-only
- **Derived**: Productivity vs entertainment ratios

#### `screentime.session.json`
- **Permission**: Screen Time access
- **Ingestion**: Real-time monitoring
- **Retention**: Short-term (24 hours)
- **Privacy**: Metadata-only
- **Derived**: Session length distribution, interruption patterns

### Notification Events
#### `notification.summary_daily.json`
- **Permission**: Notification access
- **Ingestion**: NotificationCenter observer
- **Retention**: Short-term (7 days)
- **Privacy**: Metadata-only
- **Derived**: Interruption pressure metrics

#### `notification.by_app.json`
- **Permission**: Notification access
- **Ingestion**: NotificationCenter observer
- **Retention**: Short-term (7 days)
- **Privacy**: Metadata-only
- **Derived**: Top interrupter identification

#### `notification.burst_event.json`
- **Permission**: Notification access
- **Ingestion**: Real-time analysis
- **Retention**: Short-term (24 hours)
- **Privacy**: Metadata-only
- **Derived**: Notification clustering patterns

### Device Events
#### `device.first_unlock.json`
- **Permission**: Device state monitoring
- **Ingestion**: System notifications
- **Retention**: Short-term (30 days)
- **Privacy**: Metadata-only
- **Derived**: Routine integrity markers

#### `device.late_night_pickup.json`
- **Permission**: Device state monitoring
- **Ingestion**: Motion/light sensors
- **Retention**: Short-term (7 days)
- **Privacy**: Metadata-only
- **Derived**: Sleep disruption indicators

#### `pickup.event.json`
- **Permission**: Device state monitoring
- **Ingestion**: Motion sensors
- **Retention**: Short-term (24 hours)
- **Privacy**: Metadata-only
- **Derived**: Habit loop triggers

### Attention Events
#### `attention.reaction_mode.json`
- **Permission**: Screen Time + Notifications
- **Ingestion**: Derived calculation
- **Retention**: Short-term (7 days)
- **Privacy**: Derived-only
- **Derived**: Reaction mode scoring

#### `attention.deep_work_probability.json`
- **Permission**: Screen Time + Device state
- **Ingestion**: Derived calculation
- **Retention**: Short-term (24 hours)
- **Privacy**: Derived-only
- **Derived**: Focus session quality metrics

#### `attention.fragmentation.json`
- **Permission**: Screen Time + Notifications
- **Ingestion**: Derived calculation
- **Retention**: Short-term (7 days)
- **Privacy**: Derived-only
- **Derived**: Attention fragmentation scoring

### Health Events (Optional)
#### `health.resting_hr_trend.json`
- **Permission**: HealthKit (optional)
- **Ingestion**: HealthKit API
- **Retention**: Medium-term (90 days)
- **Privacy**: Aggregated-only
- **Derived**: Recovery debt indicators

#### `health.sleep.duration.json`
- **Permission**: HealthKit (optional)
- **Ingestion**: HealthKit API
- **Retention**: Medium-term (90 days)
- **Privacy**: Aggregated-only
- **Derived**: Sleep regularity patterns

#### `health.hrv_trend.json`
- **Permission**: HealthKit (optional)
- **Ingestion**: HealthKit API
- **Retention**: Medium-term (90 days)
- **Privacy**: Aggregated-only
- **Derived**: Stress and recovery metrics

### System Events
#### `system.focus_change.json`
- **Permission**: Focus mode access
- **Ingestion**: System notifications
- **Retention**: Short-term (7 days)
- **Privacy**: Metadata-only
- **Derived**: Context transition patterns

#### `system.downtime_adherence.json`
- **Permission**: Screen Time + Focus
- **Ingestion**: Policy compliance checking
- **Retention**: Short-term (30 days)
- **Privacy**: Metadata-only
- **Derived**: Self-control boundary compliance

### App Events
#### `app.usage.top_apps.json`
- **Permission**: Screen Time
- **Ingestion**: HealthKit API
- **Retention**: Short-term (7 days)
- **Privacy**: Metadata-only
- **Derived**: Habit loop identification

#### `app.first_open_after_wake.json`
- **Permission**: Screen Time + Device state
- **Ingestion**: App launch monitoring
- **Retention**: Short-term (30 days)
- **Privacy**: Metadata-only
- **Derived**: Dopamine-hook fingerprinting

## Retention Tiers

### Short-term (24 hours - 7 days)
- Real-time operational data
- Session-level metrics
- Immediate pattern detection
- Automatic cleanup after analysis

### Medium-term (30 - 90 days)
- Trend analysis data
- Health metrics (optional)
- Routine pattern establishment
- Manual review possible

### Long-term (6+ months)
- Major life pattern changes
- System performance metrics
- Audit logs
- Explicit user consent required

## Privacy Levels

### Metadata-only
- No content, only usage statistics
- Anonymous identifiers
- Aggregated metrics
- No personal information

### Aggregated-only
- Statistical summaries
- Trend data only
- No individual data points
- Privacy-preserving by design

### Derived-only
- Computed insights only
- No raw data retention
- Mathematical transformations
- Pattern analysis results

## Implementation Requirements

### Consent Management
- Granular permission requests
- Clear data usage explanations
- Easy opt-out mechanisms
- Consent audit trails

### Data Minimization
- Collect only what's needed
- Process on-device when possible
- Automatic data cleanup
- No unnecessary retention

### Security Measures
- End-to-end encryption
- Secure key management
- Access logging
- Breach response plans

### Auditability
- Complete data lineage
- Usage transparency
- Third-party verification
- Regular compliance audits

## Future Extensions

### Phase 2 Additions
- Audio event schemas (label-only)
- Location context events
- Cross-device synchronization
- Advanced biometric integration

### Schema Evolution
- Versioned schema definitions
- Backward compatibility
- Migration strategies
- Deprecation policies

This data contract ensures NCL maintains the highest standards of privacy and user control while enabling powerful cognitive augmentation capabilities.