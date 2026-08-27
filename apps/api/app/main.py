"""FastAPI application entrypoint.

Route modules are added phase-by-phase as the pipeline is built out.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import market, research, research_intelligence, watchlist
from app.config import get_settings
from app.market_data.exceptions import (
    AuthenticationError,
    InvalidSymbolError,
    MarketDataError,
    ProviderError,
    RateLimitError,
)

settings = get_settings()

app = FastAPI(title="AI Market Desk API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router)
app.include_router(watchlist.router)
app.include_router(research.router)
app.include_router(research_intelligence.router)


@app.exception_handler(AuthenticationError)
def handle_authentication_error(request: Request, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(InvalidSymbolError)
def handle_invalid_symbol_error(request: Request, exc: InvalidSymbolError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(RateLimitError)
def handle_rate_limit_error(request: Request, exc: RateLimitError) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else {}
    return JSONResponse(status_code=503, content={"detail": str(exc)}, headers=headers)


@app.exception_handler(ProviderError)
def handle_provider_error(request: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(MarketDataError)
def handle_market_data_error(request: Request, exc: MarketDataError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.environment}
