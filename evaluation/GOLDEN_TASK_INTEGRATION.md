# NUREALCORTEXLINK Golden Task Integration Guide

## Overview

Golden Tasks are the evaluation framework for NUREALCORTEXLINK's second brain capabilities. They provide deterministic test cases to measure AI agent performance across cognitive domains: capture, organize, distill, and express.

## Architecture Integration

### Second Brain Context
Golden Tasks evaluate the CODE methodology implementation:
- **Capture**: Data ingestion and initial processing
- **Organize**: Knowledge structuring and categorization
- **Distill**: Insight generation and pattern recognition
- **Express**: Actionable output and communication

### Agent Corps Integration
Golden Tasks validate specialized AI agents:
- **Knowledge Workers**: Content analysis and categorization
- **Pattern Recognition**: Biometric and behavioral trend detection
- **Insight Synthesis**: CODE methodology application
- **Action Planning**: Task extraction and prioritization

## Task Categories

### 1. Summarization Tasks (golden_0001)
- **Purpose**: Test basic information condensation
- **Input**: Raw events or notes
- **Output**: Concise summaries
- **Evaluation**: Completeness, accuracy, conciseness

### 2. Extraction Tasks (golden_0002)
- **Purpose**: Test structured information extraction
- **Input**: Unstructured text with embedded data
- **Output**: Structured entities (action items, deadlines, assignees)
- **Evaluation**: Precision, recall, format compliance

### 3. Categorization Tasks (golden_0003)
- **Purpose**: Test knowledge organization (PARA method)
- **Input**: Mixed content items
- **Output**: Categorized by Projects/Areas/Resources/Archive
- **Evaluation**: Correctness, consistency, completeness

### 4. Insight Generation Tasks (golden_0004)
- **Purpose**: Test CODE methodology application
- **Input**: Raw experiences and observations
- **Output**: Multi-phase insights (Capture/Organize/Distill/Express)
- **Evaluation**: Phase coverage, insight quality, actionability

### 5. Pattern Recognition Tasks (golden_0005)
- **Purpose**: Test biometric and behavioral analysis
- **Input**: Time-series health and activity data
- **Output**: Patterns, severity assessment, recommendations
- **Evaluation**: Pattern detection accuracy, clinical relevance

## Implementation Details

### Task File Format
```json
{
  "id": "golden_XXXX",
  "name": "Descriptive task name",
  "input": {
    "events": [
      {"id": "e1", "text": "Input data here"}
    ]
  },
  "expected": {
    "output_field": "expected_value"
  },
  "failure_conditions": ["condition1", "condition2"]
}
```

### Evaluation Harness
The `evaluation_harness.py` script provides:
- **Task Loading**: Automatic discovery of golden_*.json files
- **Agent Simulation**: Mock AI outputs for testing
- **Scoring Algorithm**: Weighted evaluation metrics
- **Report Generation**: Comprehensive evaluation reports

### Scoring Methodology
- **Perfect Score**: 1.0 (all requirements met)
- **Passing Threshold**: 0.7 (acceptable performance)
- **Failure Conditions**: Automatic failure triggers
- **Weighted Deductions**: Partial credit for minor issues

## Integration Points

### iOS Companion App
- **EvaluationHarness Module**: Local task execution
- **Test Integration**: GoldenTasksPresenceTests validate file existence
- **CI Integration**: Automated evaluation in build pipeline

### Python Backend
- **Schema Validation**: JSON Schema validation for task files
- **Result Storage**: Evaluation results in knowledge graph
- **Trend Analysis**: Performance tracking over time

### Knowledge Graph
- **Task Results**: Stored as atomic notes with bi-directional links
- **Performance Metrics**: Historical evaluation data
- **Improvement Tracking**: CODE methodology applied to evaluation results

## Usage Examples

### Running All Tasks
```bash
python evaluation_harness.py --all --verbose
```

### Running Specific Task
```bash
python evaluation_harness.py --task-id golden_0001
```

### Generating Report
```bash
python evaluation_harness.py --all --report
```

## Future Expansion

### Planned Task Categories
- **Memory Recall**: Long-term knowledge retrieval
- **Creative Synthesis**: Novel idea generation
- **Decision Analysis**: Complex choice evaluation
- **Communication Optimization**: Message crafting and timing

### Advanced Features
- **Multi-modal Tasks**: Image, audio, and biometric data
- **Real-time Evaluation**: Streaming data processing
- **Agent Comparison**: A/B testing different AI models
- **Personalization**: User-specific task adaptation

## Quality Assurance

### Validation Checks
- **Schema Compliance**: All tasks validated against JSON schema
- **Deterministic Output**: Expected results are consistent
- **Edge Case Coverage**: Boundary conditions tested
- **Performance Benchmarks**: Baseline scores established

### Maintenance
- **Regular Updates**: Tasks evolve with system capabilities
- **Version Control**: Task versioning for compatibility
- **Documentation**: Comprehensive task descriptions
- **Community Review**: Expert validation of task quality

## Integration with Second Brain Doctrine

Golden Tasks operationalize the NUREALCORTEXLINK mission:
- **Neuro-Digital Symbiosis**: AI evaluation ensures reliable cognitive extension
- **Transactive Memory**: Tasks validate knowledge transfer between human and AI
- **Digital Gardens**: Evaluation results become part of growing knowledge ecosystem
- **CODE Methodology**: Tasks themselves follow capture-organize-distill-express pattern

This framework ensures NUREALCORTEXLINK's AI agents maintain high reliability and continuously improve cognitive augmentation capabilities.