from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
LOGIN_HTML = (Path(__file__).parent / "login.html").read_text(encoding="utf-8")

@router.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(content=LOGIN_HTML)
