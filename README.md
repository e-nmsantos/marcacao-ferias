
# Gestão de Férias 📅

**Uma aplicação de gestão de ausências/férias para equipas pequenas e médias.** Simples, visual e intuitiva.

---

## 🎯 O que é

Uma plataforma de gestão de pedidos de férias/ausências que:

- **Permite colaboradores** submeter pedidos autónomos em poucos cliques
- **Oferece gestores** aprovação/rejeição imediata e visão em tempo real
- **Fornece admin** relatórios, gestão de pessoal, backups e controlo total

Inspirado nos melhores fluxos de _MarQHR_, _Factorial_ e _Cegid Visualtime_.

---

## ✨ Funcionalidades principais

### Para colaboradores
- 📆 **Calendário interativo**: clique para selecionar datas de férias
- 📝 **Pedido simples**: tipo de ausência, comentário opcional, substituto
- 👁️ **Acompanhamento**: estado do pedido sempre visível (Pendente / Aprovado / Rejeitado)

### Para gestores
- ✅ **Aprovação/rejeição** de pedidos pendentes
- 📊 **Visão de equipa**: calendário com todas as ausências aprovadas
- ⚠️ **Alertas de conflito**: dias com muitas ausências simultâneas
- 📈 **Relatórios**: exportação em Excel com estatísticas

### Para administradores
- 👥 **Gestão de pessoal**: adicionar/editar/remover colaboradores
- 🔐 **Gestão de logins**: criar contas com roles (admin/user/viewer)
- 💾 **Backup/Restauro**: exportar/importar dados em JSON
- 🏆 **Compensações**: marcar "tolerância de ponto" que contam como feriado
- 🌍 **Feriados municipais**: seletor dinâmico para diferentes cidades em Portugal
- 🌐 **Idiomas**: suporte PT/EN (extensível)

---

## 🚀 Instalação rápida

### Pré-requisitos
- Python 3.11+
- pip ou pip3

### 1. Clonar o repositório

```bash
git clone https://github.com/e-nmsantos/marcacao-ferias.git
cd marcacao-ferias
```

### 2. Criar ambiente virtual

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

### 3. Instalar dependências

```bash
pip install -e .
```

### 4. Executar a app

```bash
streamlit run python_app.py
```

Abre automaticamente em `http://127.0.0.1:8501`

---

## 🔑 Primeiros passos

### Conta padrão
- **Utilizador**: `admin`
- **Password**: `admin123`
- **Perfil**: Administrador (tem acesso a tudo)

### Setup inicial
1. Faça login com a conta admin
2. Aceda a **Pessoal** e adicione os colaboradores
3. Aceda a **Logins** e crie contas para cada utilizador
4. Os colaboradores podem agora fazer login e submeter pedidos

---

## 📦 Configuração de dados

### SQLite (padrão)
Dados guardados em `data_store.json` na pasta do projeto.

### PostgreSQL (opcional)
Configure a variável de ambiente `DATABASE_URL`:

```bash
export DATABASE_URL="postgresql://user:password@localhost/maracao_ferias"
streamlit run python_app.py
```

---

## 🧪 Testes

Executar testes unitários:

```bash
python -m pytest -v
```

Todos os testes devem passar (4 tests).

---

## 📊 Estrutura de dados

### Vacations (Pedidos)
- `id`: UUID único
- `employee_name`: Nome do colaborador
- `start_date` / `end_date`: Período
- `absence_type`: Férias / Meio-dia / Compensação / Outro
- `status`: pending / approved / rejected
- `team`: Equipa
- `reason`: Comentário opcional
- `created_by`: Utilizador que criou

### Staff (Pessoal)
- `Nome`: Nome completo
- `Equipa`: Equipa/departamento
- `Função`: Cargo/função
- `Ativo`: Boolean

### Users (Logins)
- `username`: Identificador único
- `name`: Nome visível
- `role`: admin / user / viewer
- `password_hash`: Hash SHA-256 da password
- `staff_name`: Associação com pessoal (opcional)

---

## 🌍 Feriados em Portugal

A aplicação inclui automaticamente:
- Feriados nacionais fixos
- Feriados municipais por concelho (seletor dinâmico)
- Compensações marcadas manualmente como "Tolerância de Ponto"

---

## 🔒 Segurança

- Passwords: hash SHA-256 (não guardadas em plain text)
- Dados: JSON com backup manual ou snapshot local
- Sessões: validadas por login
- Acesso: baseado em roles (admin/user/viewer)

---

## 🛠️ Desenvolvimento

### Estrutura
```
marcacao-ferias/
├── python_app.py              # App Streamlit principal
├── vacation_app/
│   ├── storage.py             # Persistência (SQLite/PostgreSQL)
│   ├── auth.py                # Autenticação e hashing
│   ├── calendar_utils.py       # Utilitários de calendário
│   ├── constants.py            # Constantes (tipos, feriados, etc.)
│   ├── excel_export.py         # Exportação para Excel
│   ├── reports.py              # Geração de relatórios
│   └── __init__.py
├── tests/
│   └── test_core.py            # Testes unitários
├── pyproject.toml              # Metadata e dependências
├── requirements.txt            # Dependências Python
└── README.md                   # Este ficheiro
```

### Extensões futuras
- [ ] Integração com Calendário (Google, Outlook)
- [ ] Notificações por e-mail
- [ ] Mobile app (React Native)
- [ ] Dashboard de analytics mais avançado
- [ ] Integração com RH (ADP, Personio, etc.)

---

## � Deployment com Docker

Para simplificar o deployment em produção, a aplicação inclui:

- **Dockerfile**: Containerização com Python 3.11
- **docker-compose.yml**: Orquestração de app + PostgreSQL (opcional)

### Quick start

```bash
# Build e run com Docker Compose
docker-compose up -d

# Aceder ao app
http://localhost:8501

# Parar
docker-compose down
```

### Guia completo

Veja [DOCKER.md](DOCKER.md) para:
- Configuração de PostgreSQL
- Variáveis de ambiente
- Persistência de dados
- Deployment em produção
- Reverse proxy (Nginx)
- Health checks e troubleshooting

---

## �📝 Changelog

### v0.2.0 (Maio 2026)
- ✅ UI polish: premium layout, calendar prominence, responsive
- ✅ i18n: traduções PT/EN, seletor de idioma
- ✅ Acessibilidade: sr-only labels, melhor contraste
- ✅ Compensações: injetar como feriado ("Tolerância de Ponto")
- ✅ Municipal holidays: seletor dinâmico
- ✅ Error handling: DataStoreError com feedback UI

### v0.1.0
- Versão inicial com calendário, pedidos e relatórios

---

## 📞 Suporte

Para reportar bugs ou sugerir funcionalidades, abra uma [issue no GitHub](https://github.com/e-nmsantos/marcacao-ferias/issues).

---

## 📄 Licença

MIT License — veja `LICENSE` para detalhes.

---

**Desenvolvido com ❤️ para simplificar a gestão de férias.**

  `ferias.db`

  Legacy JSON imports/backups are still supported:

  `data_store.json`

  Included data:

  - Vacation requests
  - Personnel table
  - Login accounts

  Backup options (admin):

  - Download backup JSON from the `Backup` section
  - Create local snapshots in `backups/`
  - Restore from a backup JSON file

  ## Login roles

  Default users:

  - `admin` (admin)
  - `maria`, `joao` (team)
  - `consulta` (read-only)

  Passwords are now stored only as local hashes in the app source and are no longer listed in the UI or documentation.

  Permissions:

  - Admin: approve/reject, manage people, backup/restore
  - Team users: create and consult own requests
  - Read-only: consult only

  ## Team access on local network

  `run_app.bat` starts Streamlit on `127.0.0.1:8501` by default.

  To allow your team to access:

  1. Run `set ALLOW_LAN=1` in the same terminal.
  2. Run `run_app.bat` on the host machine.
  3. Share the host URL: `http://<host-ip>:8501`
  4. Ensure Windows Firewall allows inbound access to port `8501`.

  ## Deploy on Streamlit Community Cloud

  Recommended entrypoint:

  `python_app.py`

  Required dependency file:

  `requirements.txt`

  Quick steps:

  1. Create a GitHub repository and push this project.
  2. Go to `https://share.streamlit.io/`
  3. Connect your GitHub account.
  4. Click `Create app`.
  5. Select your repository, branch, and `python_app.py`.
  6. In advanced settings, keep the Python version aligned with your local environment if needed.
  7. Deploy and share the generated `streamlit.app` URL with your team.

## Persistent cloud database

The app now supports an external PostgreSQL database for durable shared persistence.

Supported configuration:

- Environment variable: `DATABASE_URL`
- Environment variable: `POSTGRES_URL`
- Streamlit secrets: `DATABASE_URL`
- Streamlit secrets section:

`[database]`

`url = "postgresql://..."`

When one of these is configured, the app uses PostgreSQL as the primary storage backend.
If none is configured, it falls back to local SQLite (`ferias.db`).

Recommended for Streamlit Community Cloud:

1. Create a managed PostgreSQL database, for example Neon.
2. Copy the connection string.
3. In Streamlit Cloud, open `App settings` > `Secrets`.
4. Add either:

`DATABASE_URL = "postgresql://..."`

or:

`[database]`

`url = "postgresql://..."`

5. Save the secrets and redeploy the app.

Important:

Without an external PostgreSQL database, Community Cloud storage can still be lost if the app instance is recreated.
  
#   m a r c a c a o - f e r i a s 
 
 
