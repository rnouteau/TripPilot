"""
Runs every case of eval/test_cases.json through the TripPilot graph and writes
eval/results/<timestamp>.json with the path taken, timings, errors and an
expected-vs-obtained comparison on the structuring fields.

Usage (from the project root):
    .venv\\Scripts\\python eval/run_eval.py
    .venv\\Scripts\\python eval/run_eval.py --no-itinerary      # skip the slow final LLM call
    .venv\\Scripts\\python eval/run_eval.py --only precise_rome invalid_city
"""
import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent / "src" / "trippilot"))

from agent import graph as agent_graph  # noqa: E402

TERMINAL_NODES = ("clarification", "weather_error", "itinerary")


def _skipped_itinerary_node(state: dict) -> dict:
    return {"final_response": "[itinerary skipped: --no-itinerary]"}


def _normalize(value):
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def _matches(expected, obtained) -> bool:
    """A list in `expected` means "any of these values" for scalar fields."""
    if isinstance(expected, list) and not isinstance(obtained, list):
        return any(_normalize(e) == _normalize(obtained) for e in expected)
    if isinstance(expected, list):
        return sorted(map(_normalize, expected)) == sorted(map(_normalize, obtained))
    return _normalize(expected) == _normalize(obtained)


def _observed_fields(state: dict, route: str) -> dict:
    budget = state.get("budget")
    if route != "itinerary" or not budget or budget == "unknown":
        budget_source = None
    else:
        budget_source = "estimated" if str(budget).startswith("~") else "user"

    return {
        "route": route,
        "city": state.get("city"),
        "country": state.get("country"),
        "start_time": state.get("start_time"),
        "end_time": state.get("end_time"),
        "number_of_days": state.get("number_of_days"),
        "number_of_travelers": state.get("number_of_travelers"),
        "month": state.get("month"),
        "missing_fields": state.get("missing_fields") or [],
        "budget": budget,
        "budget_source": budget_source,
        "desires": state.get("desires"),
        "has_desires": bool(state.get("desires")),
    }


def run_case(pilot, case: dict) -> dict:
    state = {"entry": case["query"]}
    path, error = [], None

    start = time.perf_counter()
    try:
        for chunk in pilot.graph.stream({"entry": case["query"]}, stream_mode="updates"):
            for node, update in chunk.items():
                path.append(node)
                state.update(update or {})
    except Exception:
        error = traceback.format_exc()
    duration_s = round(time.perf_counter() - start, 2)

    terminal = [n for n in path if n in TERMINAL_NODES]
    route = "crash" if error else (terminal[-1] if terminal else "incomplete")
    observed = _observed_fields(state, route)

    comparison = {}
    for field, expected in case["expected"].items():
        obtained = observed.get(field)
        comparison[field] = {"expected": expected, "obtained": obtained, "ok": _matches(expected, obtained)}

    weather = state.get("weather")
    return {
        "id": case["id"],
        "query": case["query"],
        "tags": case.get("tags", []),
        "path": path,
        "route": route,
        "missing_fields": observed["missing_fields"],
        "duration_s": duration_s,
        "error": error,
        "weather_error": weather.get("error") if isinstance(weather, dict) else None,
        "observed": observed,
        "comparison": comparison,
        "passed": error is None and all(c["ok"] for c in comparison.values()),
        "final_response": state.get("final_response"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="TripPilot agent evaluation")
    parser.add_argument("--cases", type=Path, default=EVAL_DIR / "test_cases.json")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run only these case ids")
    parser.add_argument("--no-itinerary", action="store_true",
                        help="replace the final itinerary LLM call with a stub (routing still recorded)")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]

    if args.no_itinerary:
        agent_graph.itinerary_node = _skipped_itinerary_node
    pilot = agent_graph.TripPilotGraph()

    results = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}: {case['query']}", flush=True)
        result = run_case(pilot, case)
        results.append(result)
        failed = [f for f, c in result["comparison"].items() if not c["ok"]]
        status = "PASS" if result["passed"] else "FAIL"
        print(f"    -> {status} route={result['route']} ({result['duration_s']}s)"
              + (f" mismatches={failed}" if failed else "")
              + (" CRASH" if result["error"] else ""), flush=True)

    field_mismatches: dict[str, list[str]] = {}
    for r in results:
        for field, c in r["comparison"].items():
            if not c["ok"]:
                field_mismatches.setdefault(field, []).append(r["id"])

    summary = {
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "crashes": sum(r["error"] is not None for r in results),
        "routing_ok": sum(r["comparison"].get("route", {}).get("ok", False) for r in results),
        "total_duration_s": round(sum(r["duration_s"] for r in results), 2),
        "field_mismatches": field_mismatches,
    }

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": agent_graph.OLLAMA_MODEL,
        "no_itinerary": args.no_itinerary,
        "summary": summary,
        "results": results,
    }

    results_dir = EVAL_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    out_file = results_dir / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(f"{summary['passed']}/{summary['total']} passed, "
          f"routing {summary['routing_ok']}/{summary['total']}, "
          f"{summary['crashes']} crash(es), {summary['total_duration_s']}s")
    for field, ids in field_mismatches.items():
        print(f"  {field}: {', '.join(ids)}")
    print(f"Report: {out_file}")


if __name__ == "__main__":
    main()
