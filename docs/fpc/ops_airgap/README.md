# Air-Gap Bundle Packaging

Tools and instructions for creating self-contained deployment bundles
for environments without internet connectivity.

## Overview

Air-gap bundles include:
- All Python dependencies (wheels)
- Pre-trained model checkpoints (optional)
- Configuration files
- Documentation
- Verification checksums

## Usage

```bash
# Create a bundle (requires internet for initial download)
./make_airgap_bundle.sh

# Transfer bundle to air-gapped environment
# (USB, CDS, or approved transfer mechanism)

# Install on target
pip install --no-index --find-links=wheels/ -e .
```

## Bundle Contents

```
airgap_bundle/
├── wheels/          # All pip dependencies as .whl files
├── config/          # steering.json + release policy
├── models/          # Pre-downloaded model checkpoints (optional)
├── docs/            # Offline documentation
├── checksums.sha256 # Verification hashes
└── install.sh       # Installation script
```

## Security

- All bundles include SHA-256 checksums for integrity verification
- SBOM (sbom.json) included for supply chain transparency
- Transfer via approved CDS (Cross-Domain Solution) when applicable
