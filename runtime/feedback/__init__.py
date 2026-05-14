"""Feedback synthesis cortex — consumes pillar reports, produces interpreted notes.

Authority chain: NCC/BRS/AAC drop reports into feedback-synthesis/{pillar}-reports/.
This scanner consumes them on a 5-minute interval, validates against schema,
and writes synthesis output to feedback-synthesis/synthesis/.

See feedback-synthesis/SCHEMA.md for the report contract.
"""
