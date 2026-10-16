import sys
from pathlib import Path

# Make the `synth` helper importable from test modules.
sys.path.insert(0, str(Path(__file__).parent))
