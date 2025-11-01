from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

class HabitoInput(BaseModel):
    """
    Modelo para registrar un registro de hábito o sintomatología diaria.
    Diseñado para la colección Time Series 'habitos' (Req 2).
    """
    paciente_id: str = Field(..., description="ID del paciente (metaField en Time Series)")
    ts: datetime = Field(..., description="Timestamp del registro (timeField en Time Series)")
    tipo: str = Field(..., description="Tipo de registro (ej: 'horas dormidas', 'calorías', 'síntoma X').")
    valor: float = Field(..., description="Valor numérico del registro (ej: 7.5 horas, 450.0 Kcal).")

    # Campo opcional para añadir contexto no numérico
    metadata: Optional[str] = None