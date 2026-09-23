import os

# Use OpenColorIO's built-in ACES config unless the studio sets its own OCIO.
# Set before anything creates an OpenImageIO colour config.
os.environ.setdefault("OCIO", "ocio://studio-config-latest")

# OpenCV reads this once, when it first loads: the keyer and depth engines write EXRs with it.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
