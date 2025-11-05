import React, { useState, useEffect } from 'react';

// --- Iconos de Lucide React (profesionales) ---
// (En un proyecto real, los instalarías con: npm install lucide-react)
// Aquí simulamos la importación para que el código sea legible
const User = (props) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
  </svg>
);
const ClipboardPen = (props) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect width="8" height="4" x="8" y="2" rx="1" /><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" /><path d="m21.12 2.12-4.24 4.24" />
  </svg>
);
const LineChart = (props) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M3 3v18h18" /><path d="m19 9-5 5-4-4-3 3" />
  </svg>
);
const Network = (props) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="16" y="16" width="6" height="6" rx="1" /><rect x="2" y="16" width="6" height="6" rx="1" /><rect x="9" y="2" width="6" height="6" rx="1" /><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3" /><path d="M12 12v4" />
  </svg>
);
const LogOut = (props) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" x2="9" y1="12" y2="12" />
  </svg>
);

// --- API SIMULADA ---
// En un proyecto real, esto haría llamadas `fetch` a tu API de FastAPI.
// Aquí simulamos las respuestas para que el frontend funcione en el preview.
const mockApi = {
  login: async (username, password) => {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        if (username === "agomez" && password === "pass123") {
          resolve({ token: "fake-jwt-token-agomez", user: { nombre: "Ana Gomez", rol: "Medico" } });
        } else if (username === "ljuan" && password === "pass123") {
          resolve({ token: "fake-jwt-token-ljuan", user: { nombre: "Juan Lopez", rol: "Paciente" } });
        } else {
          reject(new Error("Usuario o contraseña incorrectos"));
        }
      }, 500);
    });
  },
  getPacientes: async (token) => {
    return Promise.resolve([
      { _id: "usr-001", pii: { nombre: "Juan Lopez" } },
      { _id: "usr-002", pii: { nombre: "Maria Lopez" } },
      { _id: "usr-004", pii: { nombre: "Carlos Sanchez" } },
    ]);
  },
  getPerfil: async (pacienteId, token) => {
    const data = {
      "usr-001": { _id: "usr-001", pii: { nombre: "Juan Lopez", dni: "12345678", fecha_nac: "1997-12-20" }, paciente: { obra_social: "OSDE 210", clinico: { alergias: ["penicilina"] } } },
      "usr-002": { _id: "usr-002", pii: { nombre: "Maria Lopez", dni: "23456789", fecha_nac: "1995-05-10" }, paciente: { obra_social: "Swiss Medical", clinico: { alergias: [] } } },
      "usr-004": { _id: "usr-004", pii: { nombre: "Carlos Sanchez", dni: "34567890", fecha_nac: "2000-01-30" }, paciente: { obra_social: "OSDE 210", clinico: { alergias: ["polvo"] } } },
    };
    return Promise.resolve(data[pacienteId]);
  },
  getVisitas: async (pacienteId, token) => {
    return Promise.resolve([
      { _id: "enc-002", ts: "2025-10-15T11:00:00Z", especialidad: "Cardiología", diagnosticos: ["Control de hipercolesterolemia"] },
      { _id: "enc-001", ts: "2025-09-25T09:30:00Z", especialidad: "Gastroenterologia", diagnosticos: ["Intoxicacion alimentaria"] },
    ]);
  },
  getHabitos: async (pacienteId, token) => {
    return Promise.resolve([
      { ts: "2025-10-26T08:00:00Z", tipo: "horas dormidas", valor: 8 },
      { ts: "2025-10-26T12:30:00Z", tipo: "alimentacion", valor: 600, notas: "almuerzo" },
      { ts: "2025-10-25T07:00:00Z", tipo: "horas dormidas", valor: 6.5 },
      { ts: "2025-10-25T12:30:00Z", tipo: "alimentacion", valor: 450, notas: "almuerzo" },
    ]);
  },
  getRedCuidado: async (pacienteId, token) => {
    return Promise.resolve({
      pacienteId: pacienteId,
      medicos_tratantes: [{ nombre_medico: "Ana Gomez", rol: "Medico" }],
    });
  },
  getFamiliaresRiesgo: async (pacienteId, token) => {
    return Promise.resolve({
      pacienteId: pacienteId,
      familiares_con_riesgo: [{ nombre_familiar: "Maria Lopez", riesgo: "diabetes" }],
    });
  },
};

// --- Componente: LoginPage ---
function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("agomez");
  const [password, setPassword] = useState("pass123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { token, user } = await mockApi.login(username, password);
      onLogin(token, user);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-100">
      <div className="w-full max-w-md p-8 space-y-6 bg-white rounded-lg shadow-lg">
        <h2 className="text-3xl font-bold text-center text-sky-700">VidaSana</h2>
        <form className="space-y-6" onSubmit={handleSubmit}>
          <div>
            <label className="block text-sm font-medium text-gray-700">Usuario</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 mt-1 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-sky-500 focus:border-sky-500"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Contraseña</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 mt-1 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-sky-500 focus:border-sky-500"
              required
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full px-4 py-2 font-semibold text-white bg-sky-600 rounded-lg shadow-md hover:bg-sky-700 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:ring-offset-2 disabled:opacity-50"
          >
            {loading ? "Ingresando..." : "Ingresar"}
          </button>
        </form>
      </div>
    </div>
  );
}

// --- Componente: Dashboard ---
function Dashboard({ token, user, onLogout }) {
  const [pacientes, setPacientes] = useState([]);
  const [selectedPacienteId, setSelectedPacienteId] = useState(null);
  const [pacienteData, setPacienteData] = useState(null);
  const [activeTab, setActiveTab] = useState('perfil');

  // Cargar lista de pacientes al iniciar (si es médico)
  useEffect(() => {
    if (user.rol === "Medico") {
      mockApi.getPacientes(token).then(setPacientes);
    } else {
      // Si es paciente, se ve a sí mismo
      setSelectedPacienteId(user._id); // Asumimos que el user object tiene su ID
    }
  }, [token, user]);

  // Cargar datos del paciente seleccionado
  useEffect(() => {
    if (selectedPacienteId) {
      setActiveTab('perfil'); // Reset tab
      setPacienteData(null); // Clear data
      // Cargar todos los datos en paralelo
      Promise.all([
        mockApi.getPerfil(selectedPacienteId, token),
        mockApi.getVisitas(selectedPacienteId, token),
        mockApi.getHabitos(selectedPacienteId, token),
        mockApi.getRedCuidado(selectedPacienteId, token),
        mockApi.getFamiliaresRiesgo(selectedPacienteId, token)
      ]).then(([perfil, visitas, habitos, red, familiares]) => {
        setPacienteData({ perfil, visitas, habitos, red, familiares });
      });
    }
  }, [selectedPacienteId, token]);

  const renderTabContent = () => {
    if (!pacienteData) {
      return <div className="flex items-center justify-center h-64">Cargando datos del paciente...</div>;
    }
    
    switch(activeTab) {
      case 'perfil':
        return (
          <div>
            <h3 className="text-xl font-semibold">Perfil del Paciente</h3>
            <p><strong>Nombre:</strong> {pacienteData.perfil.pii.nombre}</p>
            <p><strong>DNI:</strong> {pacienteData.perfil.pii.dni}</p>
            <p><strong>Obra Social:</strong> {pacienteData.perfil.paciente.obra_social}</p>
            <p><strong>Alergias:</strong> {pacienteData.perfil.paciente.clinico.alergias.join(', ') || 'Ninguna'}</p>
          </div>
        );
      case 'visitas':
        return (
          <div>
            <h3 className="text-xl font-semibold">Visitas Médicas (Req 1)</h3>
            <ul className="mt-4 space-y-2">
              {pacienteData.visitas.map(v => (
                <li key={v._id} className="p-3 bg-white rounded-lg shadow-sm">
                  <p><strong>Fecha:</strong> {new Date(v.ts).toLocaleString()}</p>
                  <p><strong>Especialidad:</strong> {v.especialidad}</p>
                  <p><strong>Diagnóstico:</strong> {v.diagnosticos.join(', ')}</p>
                </li>
              ))}
            </ul>
          </div>
        );
      case 'habitos':
        return (
          <div>
            <h3 className="text-xl font-semibold">Hábitos Recientes (Req 2)</h3>
            <ul className="mt-4 space-y-2">
              {pacienteData.habitos.map(h => (
                <li key={h.ts} className="p-3 bg-white rounded-lg shadow-sm">
                  <p><strong>Fecha:</strong> {new Date(h.ts).toLocaleString()}</p>
                  <p><strong>Tipo:</strong> {h.tipo}</p>
                  <p><strong>Valor:</strong> {h.valor} {h.notas ? `(${h.notas})` : ''}</p>
                </li>
              ))}
            </ul>
          </div>
        );
      case 'red':
        return (
          <div>
            <h3 className="text-xl font-semibold">Análisis de Red (Req 3 y 5)</h3>
            <div className="mt-4 p-3 bg-white rounded-lg shadow-sm">
              <strong>Red de Cuidado (Req 3):</strong>
              <ul>
                {pacienteData.red.medicos_tratantes.map(m => (
                  <li key={m.nombre_medico}>- {m.nombre_medico} ({m.rol})</li>
                ))}
              </ul>
            </div>
            <div className="mt-4 p-3 bg-white rounded-lg shadow-sm">
              <strong>Familiares con Riesgo (Req 5):</strong>
              <ul>
                {pacienteData.familiares.familiares_con_riesgo.map(f => (
                  <li key={f.nombre_familiar}>- {f.nombre_familiar} (Riesgo: {f.riesgo})</li>
                ))}
              </ul>
            </div>
          </div>
        );
      default:
        return null;
    }
  };
  
  const TabButton = ({ id, label, icon: Icon }) => (
    <button
      onClick={() => setActiveTab(id)}
      className={`flex items-center px-4 py-2 text-sm font-medium rounded-lg ${
        activeTab === id
          ? "bg-sky-600 text-white shadow-md"
          : "text-gray-600 hover:bg-gray-200"
      }`}
    >
      <Icon className="w-5 h-5 mr-2" />
      {label}
    </button>
  );

  return (
    <div className="flex h-screen bg-slate-100">
      {/* Sidebar (Lista de Pacientes) */}
      {user.rol === "Medico" && (
        <aside className="w-64 bg-white border-r border-gray-200 p-4 space-y-2">
          <h2 className="text-lg font-semibold text-gray-800">Pacientes</h2>
          {pacientes.map(p => (
            <button
              key={p._id}
              onClick={() => setSelectedPacienteId(p._id)}
              className={`w-full text-left px-3 py-2 rounded-lg ${
                selectedPacienteId === p._id
                  ? "bg-sky-100 text-sky-700"
                  : "text-gray-700 hover:bg-slate-50"
              }`}
            >
              {p.pii.nombre}
            </button>
          ))}
        </aside>
      )}

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col">
        {/* Header */}
        <header className="flex items-center justify-between p-4 bg-white border-b border-gray-200 shadow-sm">
          <h1 className="text-2xl font-bold text-sky-700">Dashboard Profesional (Req 6)</h1>
          <div className="flex items-center space-x-4">
            <span className="text-gray-700">Hola, {user.nombre} ({user.rol})</span>
            <button onClick={onLogout} className="text-gray-500 hover:text-red-600">
              <LogOut className="w-6 h-6" />
            </button>
          </div>
        </header>
        
        {/* Contenido del Paciente */}
        <div className="flex-1 p-6 overflow-auto">
          {!selectedPacienteId ? (
            <div className="text-center text-gray-500">Seleccione un paciente para comenzar</div>
          ) : (
            <div>
              {/* Barra de Pestañas */}
              <nav className="flex space-x-2 mb-6">
                <TabButton id="perfil" label="Perfil" icon={User} />
                <TabButton id="visitas" label="Visitas" icon={ClipboardPen} />
                <TabButton id="habitos" label="Hábitos" icon={LineChart} />
                <TabButton id="red" label="Red y Riesgos" icon={Network} />
              </nav>
              {/* Contenido de la Pestaña */}
              {renderTabContent()}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

// --- Componente: App (Raíz) ---
export default function App() {
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);

  // Simula el login
  const handleLogin = (newToken, newUser) => {
    setToken(newToken);
    setUser(newUser);
    // En una app real, guardarías el token en localStorage
  };

  // Simula el logout
  const handleLogout = () => {
    setToken(null);
    setUser(null);
  };

  if (!token || !user) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return <Dashboard token={token} user={user} onLogout={handleLogout} />;
}
