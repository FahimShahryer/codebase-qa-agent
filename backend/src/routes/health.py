from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "ajentica-backend", "version": "0.1.0"}
