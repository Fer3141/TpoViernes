import os
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query#permisos comentario
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "TpoViernes")
COLLECTION = os.getenv("COLLECTION", "usuarios")

app = FastAPI(title="API TpoViernes - Historia Clínica", version="1.0")

client: AsyncIOMotorClient | None = None
db = None

@app.on_event("startup")
async def startup_event():
    global client, db
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]

@app.on_event("shutdown")
async def shutdown_event():
    if client:
        client.close()

# --------- Helpers ---------
def parse_iso(ts: str) -> datetime | None:
    # intenta parsear ISO (p.ej. "2025-09-25T09:30:00Z")
    try:
        # Soporta 'Z'
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None

def filtrar_encuentros(
    encuentros: List[dict],
    desde: Optional[str],
    hasta: Optional[str],
    especialidad: Optional[str],
    contiene: Optional[str],
) -> List[dict]:
    dts_desde = parse_iso(desde) if desde else None
    dts_hasta = parse_iso(hasta) if hasta else None
    q = (contiene or "").lower().strip()

    def match(e: dict) -> bool:
        # Fecha
        e_dt = parse_iso(e.get("ts", "")) or None
        if dts_desde and (not e_dt or e_dt < dts_desde):
            return False
        if dts_hasta and (not e_dt or e_dt > dts_hasta):
            return False
        # Especialidad
        if especialidad and (e.get("especialidad", "").lower() != especialidad.lower()):
            return False
        # Texto "contiene" (busca en diagnosticos, sintomas, notas)
        if q:
            in_diag = any(q in str(x).lower() for x in e.get("diagnosticos", []))
            in_sint = any(q in str(x).lower() for x in e.get("sintomas", []))
            in_notas = q in str(e.get("notas", "")).lower()
            if not (in_diag or in_sint or in_notas):
                return False
        return True

    return [e for e in encuentros if match(e)]

def ordenar_por_ts_desc(encuentros: List[dict]) -> List[dict]:
    def key(e: dict):
        dt = parse_iso(e.get("ts", "") or "") or datetime.min
        return dt
    return sorted(encuentros, key=key, reverse=True)

# --------- Endpoints ---------
@app.get("/usuarios/{uid}/historia")
async def listar_historia(
    uid: str,
    desde: Optional[str] = Query(None, description="ISO datetime, ej: 2025-01-01T00:00:00Z"),
    hasta: Optional[str] = Query(None, description="ISO datetime"),
    especialidad: Optional[str] = Query(None, description="p.ej. gastroenterologia"),
    contiene: Optional[str] = Query(None, description="texto en diagnosticos/sintomas/notas"),
):
    usuario = await db[COLLECTION].find_one({"_id": uid})
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    encuentros = usuario.get("paciente", {}).get("historia_clinica", []) or []
    filtrados = filtrar_encuentros(encuentros, desde, hasta, especialidad, contiene)
    return ordenar_por_ts_desc(filtrados)

@app.get("/usuarios/{uid}/historia/{enc_id}")
async def obtener_encuentro(uid: str, enc_id: str):
    usuario = await db[COLLECTION].find_one({"_id": uid})
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    encuentros = usuario.get("paciente", {}).get("historia_clinica", []) or []
    for e in encuentros:
        if e.get("id") == enc_id:
            return e
    raise HTTPException(status_code=404, detail="Encuentro no encontrado")

@app.get("/usuarios/{uid}/historia/ultima")
async def ultima_consulta(uid: str):
    usuario = await db[COLLECTION].find_one({"_id": uid})
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    encuentros = usuario.get("paciente", {}).get("historia_clinica", []) or []
    if not encuentros:
        raise HTTPException(status_code=404, detail="Sin historia clínica")
    return ordenar_por_ts_desc(encuentros)[0]
