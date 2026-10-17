"""One grading action: stop development, evaluate, clean up, then unlock."""

import asyncio
import logging
from ..database import queries as q
from ..runtime import docker as d
from ..runtime.environments import stop_development_for_grading
from ..runtime.workspaces import require_grading_workspace, archive_workspace
from .results import parse_result, classify_outcome

log = logging.getLogger(__name__)


async def grade_evaluation(connection, client, settings, request):
    evaluation = await q.get_evaluation(connection, request["id"])
    env = await q.get_environment(connection, request["user_id"])
    if (
        not evaluation
        or evaluation["finished_at"] is not None
        or not env
        or env["status"] != "grading"
        or env["current_operation_id"] != request["id"]
    ):
        return
    report = None
    archive = None
    status = "failed"
    error_code = None
    message = None
    cleanup = "stopping"
    cancelled = False
    try:
        await stop_development_for_grading(connection, client, settings, evaluation)
        cleanup = "grading"
        ex = await q.get_exercise(connection, evaluation["exercise_id"])
        path = await d.io_call(require_grading_workspace, settings, evaluation["user_id"], ex)
        archive = await d.io_call(archive_workspace, settings, evaluation["id"], path)
        container = await d.create_evaluator_container(
            client,
            settings,
            evaluation["user_id"],
            ex["id"],
            evaluation["id"],
            ex["evaluator_image"],
            path,
            ex["workspace_dir"],
        )
        outcome = await d.wait_for_evaluator(client, container.id, ex["grade_timeout_seconds"])
        if outcome.timed_out:
            status = "timeout"
            error_code = "grade_timeout"
            message = "Evaluation exceeded its time limit"
        elif outcome.oom_killed:
            error_code = "evaluator_oom"
            message = "Evaluator exceeded its memory limit"
        elif outcome.exit_code != 0:
            error_code = "evaluator_exit"
            message = "Evaluator exited without a valid report"
        else:
            data = await d.read_result_file(client, container.id, settings.max_result_bytes)
            report = parse_result(data, settings.max_result_bytes)
            status = classify_outcome(outcome, report)
    except asyncio.CancelledError:
        cancelled = True
        error_code = "worker_interrupted"
        message = "Worker interrupted; submit again"
    except Exception as exc:
        error_code = "evaluation_failed"
        message = "Unable to evaluate workspace; check files or contact an administrator"
        log.error("grading_failed evaluation=%s type=%s", evaluation["id"], type(exc).__name__)
    finally:
        try:
            containers = await d.list_managed_containers(client, settings, evaluation["user_id"])
            for item in containers:
                if item.kind == "evaluator" and item.operation_id == evaluation["id"]:
                    await d.stop_and_remove_container(client, item.id, settings.stop_grace_seconds)
            remaining = await d.list_managed_containers(client, settings, evaluation["user_id"])
            if not remaining:
                cleanup = "stopped"
        except Exception:
            log.error("grading_cleanup_pending evaluation=%s", evaluation["id"])
        await q.finalize_evaluation(
            connection,
            evaluation,
            status,
            report,
            cleanup,
            error_code,
            message,
            str(archive) if archive else None,
        )
    if cancelled:
        raise asyncio.CancelledError()
