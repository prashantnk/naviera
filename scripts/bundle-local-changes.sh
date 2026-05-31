#!/usr/bin/env bash

# scripts/bundle-local-changes.sh
# Packages all local modifications (staged, unstaged, and untracked files)
# into a single self-extracting replication script.

set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WORKSPACE_DIR"

OUTPUT_SCRIPT="apply-changes.sh"
TEMP_TAR="local_changes.tar.gz"

echo "🔍 Scanning workspace for local changes..."

# Get modified, staged, and untracked files (ignoring gitignored files)
{
    git diff --diff-filter=d --name-only
    git diff --cached --diff-filter=d --name-only
    git ls-files --others --exclude-standard
} | sort -u > temp_file_list.txt

# Filter out empty lines, the output script, and temporary files
grep -v -E "^($OUTPUT_SCRIPT|file_list\.txt|temp_file_list\.txt|$TEMP_TAR)$" temp_file_list.txt > file_list.txt || true
rm temp_file_list.txt

if [ ! -s file_list.txt ]; then
    echo "❌ No local changes (modified, staged, or untracked files) found to replicate!"
    rm file_list.txt
    exit 1
fi

echo "📦 Files to be replicated:"
cat file_list.txt

# Compress the files into a temporary tarball
echo -e "\nCreating compressed bundle..."
tar -czf "$TEMP_TAR" -T file_list.txt
rm file_list.txt

# Generate the self-extracting shell script (100% POSIX compliant for sh/dash/bash compatibility)
echo "Generating self-extracting replication script: $OUTPUT_SCRIPT..."
cat << 'EOF' > "$OUTPUT_SCRIPT"
#!/bin/sh

# ==============================================================================
# 🚢 Naviera Local Changes Replicator (Self-Extracting Installer)
# ==============================================================================
# Run this script at the root of your project folder on the target machine
# to instantly restore all local modified, staged, and untracked files.
# ==============================================================================

set -e

TARGET_DIR="$(pwd)"
echo "🚢 Restoring local changes in: $TARGET_DIR"

# Decode the embedded Base64 archive and extract it
echo "Extracting files..."
base64 -d << 'END_OF_ARCHIVE' | tar -xzf -
EOF

# Append the Base64 data of the tarball to the replication script
base64 "$TEMP_TAR" >> "$OUTPUT_SCRIPT"

# Append the tail end of the script
cat << 'EOF' >> "$OUTPUT_SCRIPT"
END_OF_ARCHIVE

echo "✅ Local modifications successfully restored!"
echo -e "\n📊 Received changes summary:"
git diff HEAD --shortstat || true
EOF

# Make it executable
chmod +x "$OUTPUT_SCRIPT"
rm "$TEMP_TAR"

echo -e "\n📊 Packed changes summary:"
git diff HEAD --shortstat || true

echo -e "\n🎉 Success! Your self-extracting replication script is ready at: \033[1;33m./$OUTPUT_SCRIPT\033[0m"
echo "You can now copy this single file's contents and run it on any other machine."
