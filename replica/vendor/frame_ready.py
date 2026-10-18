"""Wait for complete PNG files after AE dispatch, with a bounded deadline."""
import time
from PIL import Image


def wait_for_frames(paths, timeout=30, interval=0.25):
    pending = set(paths)
    deadline = time.monotonic() + timeout
    errors = {}
    while pending:
        for path in list(pending):
            try:
                # verify checks PNG chunk integrity, including the final IEND.
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    image.load()
                pending.remove(path)
                errors.pop(path, None)
            except (OSError, SyntaxError) as error:
                errors[path] = str(error)
        if not pending:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('Incomplete frames after deadline: ' +
                               repr({str(p): errors[p] for p in pending}))
        time.sleep(interval)
