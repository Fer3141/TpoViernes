from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# --- Modelos Pydantic ADAPTADOS (Copiados de tu main.py) ---
class PIIModel(BaseModel):
    # ... (contenido de PIIModel)
    dni: str
    nombre: str
    email: str
    telefono: str
    direccion: str
    fecha_nac: str
    genero: str
    pais: str

class HorarioModel(BaseModel):
    # ... (contenido de HorarioModel)
    dia: str
    inicio: str 
    fin: str 

class CentroModel(BaseModel):
    # ... (contenido de CentroModel)
    nombre: str
    horarios: List[HorarioModel] = []

class MedicoModel(BaseModel):
    # ... (contenido de MedicoModel)
    matricula: Optional[str] = None 
    especialidad: Optional[List[str]] = None 
    centros: Optional[List[CentroModel]] = None

class PacienteClinicoModel(BaseModel):
    # ... (contenido de PacienteClinicoModel)
    grupo_sanguineo: Optional[str] = None
    alergias: Optional[List[str]] = None
    antecedentes: Optional[List[str]] = None

class PacienteModel(BaseModel):
    # ... (contenido de PacienteModel)
    obra_social: Optional[str] = None
    numero_afiliado: Optional[str] = None
    clinico: Optional[PacienteClinicoModel] = None
    ultima_consulta_id: Optional[str] = None
    riesgos_activos_count: Optional[int] = None
    habitos_ultima_actualizacion: Optional[str] = None
    riesgo_calculado: Optional[str] = None # Campo añadido del Req 5
    score_riesgo: Optional[int] = None
    
class AuthModel(BaseModel):
    # ... (contenido de AuthModel)
    username: str
    password: str = Field(alias='pass')

class UsuarioInput(BaseModel):
    # ... (contenido de UsuarioInput)
    id: Optional[str] = None 
    auth: AuthModel
    roles: List[str] 
    pii: PIIModel 
    paciente: Optional[PacienteModel] = None 
    medico: Optional[MedicoModel] = None

class UsuarioUpdate(BaseModel):
    # ... (contenido de UsuarioUpdate)
    auth: Optional[AuthModel] = None
    roles: Optional[List[str]] = None
    pii: Optional[PIIModel] = None
    paciente: Optional[PacienteModel] = None
    medico: Optional[MedicoModel] = None