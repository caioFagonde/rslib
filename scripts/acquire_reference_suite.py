"""Explicit live acquisition of preselected cases; failures retain the pinned inventory."""

import argparse
import asyncio
import json
from pathlib import Path

from rslib.reference_capture import ReferencePlan, acquire_reference
from rslib.references import register_reference


async def main(args):
    plan = ReferencePlan.model_validate_json(args.plan.read_bytes())
    failures = []
    for case in plan.cases:
        if args.case and case.id not in args.case:
            continue
        print(f"START {case.id}", flush=True)

        def progress(event, identifier=case.id):
            print(f"{identifier}: {event['phase']}: {event['message']}", flush=True)

        try:
            result = await acquire_reference(
                args.plan, case.id, args.data, args.snapshots, progress=progress
            )
            register_reference(args.catalog, args.data, args.snapshots / case.id / "snapshot.json")
            print(f"FINISHED {case.id} {result['run_id']}", flush=True)
        except Exception as error:
            failures.append({"case": case.id, "error": str(error), "type": type(error).__name__})
            print(f"FAILED {case.id}: {type(error).__name__}: {error}", flush=True)
    print(json.dumps({"failures": failures}, indent=2), flush=True)
    return bool(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path, default=Path("docs/reference-projects/selection-plan.json")
    )
    parser.add_argument(
        "--catalog", type=Path, default=Path("docs/reference-projects/catalog.json")
    )
    parser.add_argument("--snapshots", type=Path, default=Path("docs/reference-projects/snapshots"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--case", action="append")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
