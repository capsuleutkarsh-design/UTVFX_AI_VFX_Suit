import os

# Use OpenColorIO's built-in ACES config unless the studio sets its own OCIO.
# Set before anything creates an OpenImageIO colour config.
os.environ.setdefault("OCIO", "ocio://studio-config-latest")
