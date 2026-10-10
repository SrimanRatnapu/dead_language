"""Small file helpers shared by the usage file and the scripts that write results."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path | str, data: Any) -> None:
    """Write to a temp file in the same folder, then rename over the target, so readers never see half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    for attempt in range(5):   # Windows: replace fails while another process has the file open
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05)
