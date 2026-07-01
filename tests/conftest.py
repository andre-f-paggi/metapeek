import sys
from pathlib import Path

# Make the project root importable so tests can `import taskbar_config`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
