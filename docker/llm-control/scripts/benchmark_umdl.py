#!/usr/bin/env python3
"""Run one LLM/UMDL benchmark through /mission/plan.

The benchmark forces the LLM path, so obstacle samples do not use the runtime
Safety Fast Path. This makes model-to-model comparisons meaningful.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from evaluation_metrics import evaluate_rows, load_jsonl


def _extract_attempt_flags(
    detail: Any,
) -> tuple[bool, bool, dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(detail, dict):
        return False, False, None, {}

    attempts = detail.get("attempts") or []

    generation_ir = (
        detail.get("generation_ir")
        if isinstance(detail.get("generation_ir"), dict)
        else None
    )

    parse_ok = generation_ir is not None
    schema_ok = False
    usage: dict[str, Any] = {}

    if attempts and isinstance(attempts[-1], dict):
        last = attempts[-1]

        parse_ok = parse_ok or (
            "parse_error" not in last
            and "model_error" not in last
        )

        schema_ok = (
            parse_ok
            and last.get("generation_schema_error_count", 1) == 0
        )

        if isinstance(last.get("usage"), dict):
            usage = last["usage"]

    return parse_ok, schema_ok, generation_ir, usage


async def _one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    base_url: str,
    sample: dict[str, Any],
) -> dict[str, Any]:

    inp = sample["input"]

    payload = {
        "instruction": inp["command"],
        "runtime_context": inp.get("runtime_context", {}),
        "available_capabilities": inp.get(
            "available_capabilities", []
        ),
        "mission_id": sample["target"].get(
            "mission_id",
            sample["group_id"],
        ),
        "force_llm": True,
    }

    #
    # IMPORTANT:
    # Semaphore 대기시간을 모델 latency에 포함하지 않는다.
    #
    async with sem:
        started = time.perf_counter()

        try:
            response = await client.post(
                f"{base_url.rstrip('/')}/mission/plan",
                json=payload,
            )

            elapsed = (
                time.perf_counter() - started
            ) * 1000.0

        except Exception as exc:
            elapsed = (
                time.perf_counter() - started
            ) * 1000.0

            return {
                "id": sample["id"],
                "group_id": sample["group_id"],
                "family": sample.get(
                    "metadata", {}
                ).get("canonical_family"),
                "request_success": False,
                "parse_ok": False,
                "generation_schema_ok": False,
                "prediction": None,
                "error": f"{type(exc).__name__}: {exc}",
                "timing_ms": {
                    "request_total_ms": round(
                        elapsed, 3
                    )
                },
            }

    try:
        body = response.json()

    except Exception:
        body = {
            "raw": response.text[:2000]
        }

    #
    # 정상 응답
    #
    if (
        response.status_code < 400
        and isinstance(body, dict)
        and isinstance(body.get("plan"), dict)
    ):

        attempts = (
            body.get("validation", {})
            .get("attempts", [])
        )

        usage = (
            attempts[-1].get("usage", {})
            if attempts
            and isinstance(attempts[-1], dict)
            else {}
        )

        return {
            "id": sample["id"],
            "group_id": sample["group_id"],
            "family": sample.get(
                "metadata", {}
            ).get("canonical_family"),

            "request_success": True,
            "parse_ok": True,
            "generation_schema_ok": True,

            "prediction": body["plan"],

            "generation_ir": (
                body.get("generation", {})
                .get("ir")
            ),

            "timing_ms": {
                **(body.get("timing_ms") or {}),
                "request_total_ms": round(
                    elapsed, 3
                ),
            },

            "usage": usage,
            "http_status": response.status_code,
        }

    #
    # 오류 응답
    #
    if isinstance(body, dict):
        detail = body.get("detail")
        if detail is None:
            detail = body
    else:
        detail = body

    parse_ok, schema_ok, ir, usage = (
        _extract_attempt_flags(detail)
    )

    return {
        "id": sample["id"],
        "group_id": sample["group_id"],
        "family": sample.get(
            "metadata", {}
        ).get("canonical_family"),

        "request_success": False,
        "parse_ok": parse_ok,
        "generation_schema_ok": schema_ok,

        "prediction": None,
        "generation_ir": ir,
        "error": detail,

        "timing_ms": {
            "request_total_ms": round(
                elapsed, 3
            )
        },

        "usage": usage,
        "http_status": response.status_code,
    }


async def run(args: argparse.Namespace) -> int:

    rows = load_jsonl(
        args.dataset_root
        / "raw"
        / f"{args.split}.jsonl"
    )


    # limit이 family 수보다 큰 경우 나머지 채우기
    if args.limit:
        selected = []
        seen_families = set()

        # 1차: 서로 다른 family 우선
        for row in rows:
            family = (
                row.get("metadata", {})
                .get("canonical_family")
            )

            if family not in seen_families:
                selected.append(row)
                seen_families.add(family)

            if len(selected) >= args.limit:
                break

        # limit이 family 수보다 큰 경우 나머지 채우기
        if len(selected) < args.limit:
            selected_ids = {
                row["id"] for row in selected
            }

            for row in rows:
                if row["id"] in selected_ids:
                    continue

                selected.append(row)

                if len(selected) >= args.limit:
                    break
        rows = selected

    if not rows:
        print("No benchmark samples found.")
        return 1

    schema = json.loads(
        (
            args.dataset_root
            / "schema"
            / "umdl-0.1.schema.json"
        ).read_text(encoding="utf-8")
    )

    print()
    print("==========================================")
    print(" UMDL Benchmark")
    print("==========================================")
    print(f"Split       : {args.split}")
    print(f"Samples     : {len(rows)}")
    print(f"Concurrency : {args.concurrency}")
    print(f"Base URL    : {args.base_url}")
    print("Force LLM   : True")
    print("==========================================")
    print(flush=True)

    timeout = httpx.Timeout(
        connect=10.0,
        read=args.timeout,
        write=30.0,
        pool=10.0,
    )

    async with httpx.AsyncClient(
        timeout=timeout
    ) as client:

        #
        # llm-control 상태 확인
        #
        model_meta: dict[str, Any] = {}

        try:
            h = await client.get(
                f"{args.base_url.rstrip('/')}/health"
            )

            if h.status_code < 400:
                model_meta = h.json()

        except Exception as exc:
            print(
                f"[WARN] Could not read /health: {exc}",
                flush=True,
            )

        sem = asyncio.Semaphore(
            args.concurrency
        )

        #
        # 진행률 출력용
        #
        progress_lock = asyncio.Lock()
        completed = 0

        async def run_one(
            index: int,
            row: dict[str, Any],
        ) -> tuple[int, dict[str, Any]]:

            nonlocal completed

            result = await _one(
                client,
                sem,
                args.base_url,
                row,
            )

            async with progress_lock:
                completed += 1

                timing = (
                    result.get("timing_ms", {})
                    .get("request_total_ms", 0.0)
                )

                family = (
                    result.get("family")
                    or "unknown"
                )

                sample_id = (
                    result.get("id")
                    or f"sample-{index}"
                )

                if result.get("request_success"):
                    status = "PASS"
                else:
                    status = "FAIL"

                print(
                    f"[{completed}/{len(rows)}] "
                    f"{sample_id} "
                    f"family={family} "
                    f"{status} "
                    f"{timing:.1f} ms",
                    flush=True,
                )

                if not result.get(
                    "request_success"
                ):
                    error = result.get("error")

                    if error:
                        error_text = str(error)

                        if len(error_text) > 300:
                            error_text = (
                                error_text[:300]
                                + "..."
                            )

                        print(
                            f"    error={error_text}",
                            flush=True,
                        )

            #
            # index를 같이 반환해서
            # gather 이후 원래 dataset 순서 유지
            #
            return index, result

        started_all = time.perf_counter()

        indexed_predictions = (
            await asyncio.gather(
                *[
                    run_one(i, row)
                    for i, row in enumerate(rows)
                ]
            )
        )

        total_elapsed = (
            time.perf_counter()
            - started_all
        )

    #
    # concurrency > 1에서도
    # dataset 원래 순서 복원
    #
    indexed_predictions.sort(
        key=lambda x: x[0]
    )

    predictions = [
        result
        for _, result
        in indexed_predictions
    ]

    print()
    print(
        f"Completed {len(predictions)} samples "
        f"in {total_elapsed:.2f} sec"
    )
    print()

    #
    # 평가
    #
    metrics = evaluate_rows(
        rows,
        predictions,
        schema,
    )

    model_name = (
        args.model_name
        or model_meta.get("huggingface_model")
        or model_meta.get("ollama_model")
        or "unknown-model"
    )

    timestamp = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )

    safe_model = "".join(
        c
        if c.isalnum()
        or c in "._-"
        else "_"
        for c in str(model_name)
    )[:120]

    safe_tag = "".join(
        c
        if c.isalnum()
        or c in "._-"
        else "_"
        for c in str(args.run_tag)
    )[:80]

    suffix = (
        f"_{safe_tag}"
        if safe_tag
        else ""
    )

    run_dir = (
        args.output_dir
        / (
            f"{timestamp}_"
            f"{safe_model}_"
            f"{args.split}"
            f"{suffix}"
        )
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    #
    # 개별 prediction 저장
    #
    pred_path = (
        run_dir
        / "predictions.jsonl"
    )

    with pred_path.open(
        "w",
        encoding="utf-8",
    ) as f:

        for row in predictions:
            f.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                )
                + "\n"
            )

    #
    # 전체 report
    #
    report = {
        "run": {
            "timestamp_utc": timestamp,
            "model": model_name,
            "split": args.split,
            "sample_count": len(rows),
            "base_url": args.base_url,
            "concurrency": args.concurrency,
            "force_llm": True,
            "run_tag": args.run_tag,
            "few_shot_enabled": (
                model_meta.get(
                    "umdl_few_shot"
                )
            ),
            "family_hints_enabled": (
                model_meta.get(
                    "umdl_family_hints"
                )
            ),
            "benchmark_wall_time_sec": round(
                total_elapsed,
                3,
            ),
        },
        "metrics": metrics,
    }

    (
        run_dir
        / "metrics.json"
    ).write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print(f"Saved: {run_dir}")

    return 0


def main() -> None:

    p = argparse.ArgumentParser()

    p.add_argument(
        "--base-url",
        default=os.environ.get(
            "LLM_CONTROL_BASE_URL",
            "http://127.0.0.1:8080",
        ),
    )

    p.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(
            os.environ.get(
                "UMDL_DATASET_ROOT",
                "/app/dataset",
            )
        ),
    )

    p.add_argument(
        "--split",
        choices=[
            "train",
            "validation",
            "test",
        ],
        default="test",
    )

    p.add_argument(
        "--limit",
        type=int,
        default=0,
    )

    p.add_argument(
        "--concurrency",
        type=int,
        default=1,
    )

    p.add_argument(
        "--timeout",
        type=float,
        default=210.0,
    )

    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "UMDL_RESULTS_DIR",
                "/app/results",
            )
        ),
    )

    p.add_argument(
        "--model-name",
        default="",
    )

    p.add_argument(
        "--run-tag",
        default=os.environ.get(
            "UMDL_BENCHMARK_RUN_TAG",
            "",
        ),
    )

    args = p.parse_args()

    raise SystemExit(
        asyncio.run(run(args))
    )


if __name__ == "__main__":
    main()