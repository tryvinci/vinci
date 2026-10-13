# Import helper: mac_local_build_stub lives alongside tests (test-only PATH stubs).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
