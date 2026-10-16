"""
Flinza Outreacher — Pterodactyl / Nexcloud Entrypoint (main.py)
"""
import os
import sys
import zipfile

# Auto-extract bundle if present
if os.path.exists("bundle.zip"):
    print("📦 Detected bundle.zip — extracting codebase...")
    try:
        with zipfile.ZipFile("bundle.zip", "r") as z:
            z.extractall(".")
        print("✅ Extraction complete.")
    except Exception as e:
        print(f"⚠️ Extraction notice: {e}")

try:
    import app
    if __name__ == "__main__":
        app.main()
except Exception as e:
    print(f"Fatal error starting Flinza: {e}")
    raise
