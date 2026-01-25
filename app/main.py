"""FastAPI main application."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import engine, Base
from app.routers import auth, dashboard, modules, submissions, grades, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Create database tables
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Course Material Review Portal",
    description="Crowdsource reviews of course materials for Agentic AI Systems course",
    version="1.0.0",
    lifespan=lifespan,
)

# Add session middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=86400 * 7,  # 7 days
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(modules.router)
app.include_router(submissions.router)
app.include_router(grades.router)
app.include_router(admin.router, prefix="/admin", tags=["admin"])


# Templates
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Landing page with Google Sign-In."""
    user_id = request.session.get("user_id")
    if user_id:
        return HTMLResponse(
            status_code=303, headers={"Location": "/dashboard"}
        )
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway."""
    return {"status": "healthy"}


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 handler."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "Not found"},
        )
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error": "Page not found", "status_code": 404},
        status_code=404,
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    """Custom 500 handler."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error": "Something went wrong", "status_code": 500},
        status_code=500,
    )
