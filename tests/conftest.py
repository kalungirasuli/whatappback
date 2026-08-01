import sys
from unittest.mock import MagicMock

# ultralytics/torch has Python 3.14 compatibility issues,
# so we mock them before any test imports trigger them.
_ultralytics_mock = MagicMock()
_ultralytics_mock.YOLO = MagicMock()
sys.modules["ultralytics"] = _ultralytics_mock
sys.modules["ultralytics.utils"] = MagicMock()
sys.modules["ultralytics.utils.patches"] = MagicMock()
