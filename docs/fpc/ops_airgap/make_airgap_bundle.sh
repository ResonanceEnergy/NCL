#!/usr/bin/env bash
# make_airgap_bundle.sh — Create self-contained air-gap deployment bundle
set -euo pipefail

BUNDLE_DIR="airgap_bundle"
WHEELS_DIR="$BUNDLE_DIR/wheels"
CONFIG_DIR="$BUNDLE_DIR/config"
DOCS_DIR="$BUNDLE_DIR/docs"

echo "=== Air-Gap Bundle Builder ==="

# Clean previous bundle
rm -rf "$BUNDLE_DIR"
mkdir -p "$WHEELS_DIR" "$CONFIG_DIR" "$DOCS_DIR"

# Download all wheels
echo "[1/6] Downloading Python wheels..."
pip download -d "$WHEELS_DIR" -e ".[dev]" --python-version 3.11 --only-binary=:all:

# Copy config
echo "[2/6] Copying configuration..."
cp -r config/* "$CONFIG_DIR/" 2>/dev/null || echo "  No config files found"
cp ops/ReleasePolicy.yaml "$CONFIG_DIR/" 2>/dev/null || true

# Copy docs
echo "[3/6] Copying documentation..."
cp -r docs/* "$DOCS_DIR/" 2>/dev/null || echo "  No docs found"
cp README.md "$BUNDLE_DIR/" 2>/dev/null || true

# Generate SBOM
echo "[4/6] Generating SBOM..."
if command -v syft &> /dev/null; then
    syft dir:. -o spdx-json > "$BUNDLE_DIR/sbom.json"
else
    echo "  syft not found — skipping SBOM (install: curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh)"
fi

# Generate checksums
echo "[5/6] Generating checksums..."
find "$BUNDLE_DIR" -type f ! -name "checksums.sha256" -exec sha256sum {} \; > "$BUNDLE_DIR/checksums.sha256"

# Create install script
echo "[6/6] Creating install script..."
cat > "$BUNDLE_DIR/install.sh" << 'INSTALL_EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "Installing Future Predictor Council (air-gapped)..."
echo "Verifying checksums..."
sha256sum -c checksums.sha256 --quiet || { echo "CHECKSUM VERIFICATION FAILED"; exit 1; }
echo "Installing Python packages..."
pip install --no-index --find-links=wheels/ future-predictor-council
echo "Installation complete."
INSTALL_EOF
chmod +x "$BUNDLE_DIR/install.sh"

# Summary
BUNDLE_SIZE=$(du -sh "$BUNDLE_DIR" | cut -f1)
WHEEL_COUNT=$(find "$WHEELS_DIR" -name "*.whl" | wc -l)
echo ""
echo "=== Bundle Complete ==="
echo "  Location: $BUNDLE_DIR/"
echo "  Size:     $BUNDLE_SIZE"
echo "  Wheels:   $WHEEL_COUNT packages"
echo "  Transfer this directory to the target environment."
