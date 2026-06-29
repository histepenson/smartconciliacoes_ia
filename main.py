from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import traceback

from routers.fiscal_router import router as fiscal_router
from routers.financeiro_router import router as financeiro_router
from routers.bancario_router import router as bancario_router
from routers.estoque_router import router as estoque_router
from routers.analise_router import router as analise_router

app = FastAPI(
    title="SmartConciliacoes IA",
    description="""
Engine de matching/diferencas (fiscal, financeiro, bancario, estoque) e
diagnostico de divergencias, consumido via API pelo conciliacao-api.
""",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Erro interno do servidor: {str(exc)}"},
    )


@app.get("/", tags=["Health"])
def health():
    return {"status": "ok", "app": "smartconciliacoes_ia"}


app.include_router(fiscal_router, prefix="/api")
app.include_router(financeiro_router, prefix="/api")
app.include_router(bancario_router, prefix="/api")
app.include_router(estoque_router, prefix="/api")
app.include_router(analise_router, prefix="/api")
