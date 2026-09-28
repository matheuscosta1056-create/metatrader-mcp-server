from typing import Callable, Iterable


def run_batch(ids: Iterable, operation: Callable, label: str) -> dict:
    """
    Run an order operation on each ID and report every failure.

    The batch is only successful when every single operation succeeded.
    """
    done = []
    failed = []
    for id in ids:
        result = operation(id)
        if result.get("error", True):
            failed.append({ "id": int(id), "message": result.get("message") })
        else:
            done.append(int(id))

    if failed:
        details = "; ".join(f"{f['id']}: {f['message']}" for f in failed)
        return {
            "error": True,
            "message": f"{label}: {len(done)} done, {len(failed)} FAILED. {details}",
            "data": { "done": done, "failed": failed },
        }

    return {
        "error": False,
        "message": f"{label}: {len(done)} done",
        "data": { "done": done, "failed": [] },
    }
