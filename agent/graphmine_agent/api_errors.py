"""One HTTP error policy, preserving status, retry hints and history context."""

import sqlite3
from fastapi import Request
from fastapi.responses import JSONResponse

from .account_api import account_response
from .errors import AnalyticsError
from .catalog import CatalogError
from .database import QueueCapacityError, RecordNotFound
from .execution import ExecutionError
from .identity import AccountError
from .llm import LLMError
from .planning import PlanValidationError


def register_error_handlers(app):
    @app.exception_handler(AccountError)
    async def account_error_handler(_request, error):
        return account_response(error)

    @app.exception_handler(AnalyticsError)
    async def analytics_error_handler(
        _request: Request, error: AnalyticsError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": str(error), **({"details": error.details} if error.details is not None else {})}},
        )

    @app.exception_handler(RecordNotFound)
    async def not_found_handler(
        _request: Request, error: RecordNotFound
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"code": "not_found", "message": str(error).strip("'")},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    @app.exception_handler(PlanValidationError)
    async def plan_error_handler(
        _request: Request, error: PlanValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "turn_id": getattr(error, "history_turn_id", None),
                "error": {
                    "code": "invalid_execution_plan",
                    "message": str(error),
                    "details": error.errors,
                },
            },
        )

    @app.exception_handler(QueueCapacityError)
    async def queue_capacity_handler(
        _request: Request, error: QueueCapacityError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "5"},
            content={
                "turn_id": getattr(error, "history_turn_id", None),
                "error": {
                    "code": "job_queue_full",
                    "message": str(error),
                    "details": {
                        "limit": error.limit,
                        "pending": error.pending,
                        "requested": error.requested,
                    },
                },
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "invalid_request", "message": str(error)},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    @app.exception_handler(CatalogError)
    async def catalog_error_handler(
        _request: Request, error: CatalogError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "catalog_error", "message": str(error)},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    @app.exception_handler(LLMError)
    async def llm_error_handler(_request: Request, error: LLMError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"code": "llm_unavailable", "message": str(error)},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    @app.exception_handler(ExecutionError)
    async def execution_error_handler(
        _request: Request, error: ExecutionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"code": error.code, "message": str(error)},
                "turn_id": getattr(error, "history_turn_id", None),
            },
        )

    @app.exception_handler(sqlite3.Error)
    async def storage_error_handler(
        _request: Request, _error: sqlite3.Error
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "storage_unavailable",
                    "message": "The metadata store is unavailable. Check storage and job status before retrying.",
                }
            },
        )

