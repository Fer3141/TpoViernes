from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- Subestructuras de la Visita ---

class SignosVitalesModel(BaseModel):
    """Modelo para los signos vitales."""
    PA: Optional[str] = None # description="Presión Arterial (ej: 120/80)")
    FC: Optional[int] = None # description="Frecuencia Cardíaca")
    # Puedes añadir más campos como Temperatura, Saturación, etc.

class RecetaModel(BaseModel):
    """Modelo para cada medicamento recetado."""
    farmaco: Optional[str] = None  # description="Nombre del medicamento"
    dosis: Optional[str] = None  # description="Dosis y frecuencia"

class AdjuntoModel(BaseModel):
    """Modelo para referencias a documentos adjuntos."""
    tipo: Optional[str] = None  # description="Tipo de archivo (ej: pdf, jpg)")
    ref: Optional[str] = None  # description="Referencia o URL al archivo (ej: s3://...)")

# --- Modelo de Entrada Principal ---

class VisitaInput(BaseModel):
    """
    Modelo maestro para registrar una nueva Visita Médica.
    Corresponde a la Historia Clínica No Estructurada (Req 1 / Contexto general).
    """
    id: str # description="ID único de la visita (ej: enc-003)")
    paciente_id: str  # description="ID del paciente al que pertenece la visita")
    medico_id: str #description="ID del médico que realiza la visita")
    ts: datetime # description="Timestamp de la visita (ISO 8601)")
    especialidad: str
    
    # Información clínica
    diagnosticos: Optional[List[str]] = None
    sintomas: Optional[List[str]] = None
    signos: Optional[SignosVitalesModel] = None
    recetas: Optional[List[RecetaModel]] = None
    
    # Notas y archivos
    adjuntos: Optional[List[AdjuntoModel]] = None
    notas: Optional[str] = None
    
    # Metadatos
    version: Optional[int] = 1 # Para control de versiones de la historia clínica
    
    class Config:
        # Permite que se use 'id' en Python y '_id' en MongoDB/JSON
        allow_population_by_field_name = True