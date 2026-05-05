# Release Notes — v0.2.0

**Release Date**: Maio 2026  
**Status**: ✅ Production Ready

---

## 🎯 Overview

**Gestão de Férias v0.2.0** é uma aplicação de gestão de ausências/férias para equipas pequenas e médias, com suporte a múltiplos idiomas, containerização Docker, logging de auditoria estruturado, e testes e2e abrangentes.

---

## ✨ Funcionalidades Novas (v0.2.0)

### 1. 🎨 UI/UX Premium
- Layout profissional com gradientes e espaçamento refinado
- Calendário interativo como elemento central
- Botões primários destacados (azul escuro, sombra suave)
- Design responsivo para desktop e tablets
- Paleta de cores melhorada (contraste WCAG AA+)

### 2. 🌍 Internationalization (i18n)
- Suporte a PT/EN com seletor dinâmico no sidebar
- Tradução de todos os elementos principais (títulos, botões, labels)
- Sistema extensível com dict-based `TRANSLATIONS`
- Helper `t(key)` para lookup de texto por idioma
- Suporte a mais idiomas no futuro (ES, FR, etc.)

### 3. ♿ Acessibilidade
- `sr-only` labels para leitores de ecrã
- Melhor contraste (AA+ WCAG)
- ARIA labels explícitos em inputs
- Navegação por teclado otimizada
- Feedback visual claro para estados de formulário

### 4. 💼 Compensações ("Tolerância de Ponto")
- Marcar ausências como compensação via admin
- Compensações injetadas como feriados (não contam como dias úteis)
- Visível no calendário com label "💻 Tolerância"
- Auditável e rastreável

### 5. 🏪 Feriados Municipais Dinâmicos
- Seletor dinâmico de município no filtro de relatórios
- Suporta feriados locais de Lisboa, Covilhã, etc.
- Integrado nos cálculos de dias úteis
- Configurável via `MUNICIPAL_HOLIDAYS` em constants.py

### 6. 📊 Tratamento de Erros Robusto
- `DataStoreError` estruturado com mensagens user-friendly
- Feedback visual em português e inglês
- Validação de staff/users com mensagens claras
- Try/catch em mutações com logging automático

### 7. 📋 Logging de Auditoria Estruturado
- Módulo `vacation_app/audit.py` centralizado
- Formato JSONL (line-delimited JSON) para logs
- Tracking de: criar, atualizar, deletar, mudar status, aprovar, rejeitar
- Detalhes automáticos: timestamp, username, entity_id, status
- Arquivo de logs: `audit_logs/audit.jsonl`
- Util para compliance e forensics

### 8. 🐳 Containerização Docker
- **Dockerfile** com Python 3.11 slim base
- **docker-compose.yml** com app + PostgreSQL opcional
- Health checks integrados
- `.dockerignore` para builds eficientes
- Variáveis de ambiente para configuração
- Guia completo em [DOCKER.md](DOCKER.md)

### 9. ✅ Testes End-to-End (E2E)
- Teste `test_complete_vacation_workflow`: criar staff → criar login → submeter pedido → aprovar → validar persistência
- Teste `test_multiple_vacation_requests`: múltiplas requisições simultâneas
- Teste `test_absence_type_handling`: todos os tipos de ausência
- Todos os 3 testes passando
- Executáveis com: `pytest tests/test_e2e.py -v`

### 10. 🚀 Performance Optimization
- **Caching com TTL**: `cached_portugal_holidays()` com 1 hora de cache
- **Lazy-loading**: `lazy_load_vacations()` filtra por mês (±1 mês)
- **DataFrame otimizado**: `optimize_dataframe_display()` com `hide_index=True`
- **Month navigation**: `build_months_list()` cached
- Reduz cálculos repetitivos e uso de memória

---

## 🔧 Melhorias Técnicas

### Backend
- Integração com PostgreSQL via `DATABASE_URL`
- Fallback para SQLite local se DB não configurada
- Validação robusta de dados em storage.py
- Transações ACID com lock manager

### Frontend (Streamlit)
- Gerenciamento de estado com `st.session_state`
- Pattern de "pending state" para evitar widget-bound mutations
- Callbacks para ações síncronas
- CSS injection para styling customizado

### DevOps
- CI/CD pipeline: GitHub Actions com pytest
- Dockerfile multi-stage ready (setup para otimização futura)
- docker-compose com health checks
- `.gitignore` e `.dockerignore` otimizados

### Testing
- Unit tests: `tests/test_core.py` (4 testes)
- E2E tests: `tests/test_e2e.py` (3 testes)
- Fixture de temp DB para testes isolados
- Coverage de fluxo completo: autenticação → requisição → aprovação → relatório

---

## 📦 Packaging & Distribution

### Python Package
- Configuração setuptools em `pyproject.toml`
- Versão: `0.2.0`
- Instalação: `pip install -e .`
- Entrypoint: `streamlit run python_app.py`

### Dependências Core
```
streamlit>=1.28.0
pandas>=2.0.0
openpyxl>=3.1.0
psycopg2-binary>=2.9.0  # PostgreSQL driver
psycopg_pool>=1.0.0     # Connection pooling
```

### Docker
- Base: `python:3.11-slim`
- Porta: `8501` (Streamlit)
- Healthcheck: `/_stcore/health`
- Logs: JSONL estruturado

---

## 🔐 Security

### Authentication
- SHA-256 password hashing (via `vacation_app/auth.py`)
- Verification timing-safe
- Roles: admin, user, viewer
- Login state in `st.session_state`

### Audit Trail
- Todas as mutações logged em `audit_logs/audit.jsonl`
- Immutable JSONL format
- Detalhes: quem, quando, o quê, resultado
- Suporta compliance requirements

### Data Validation
- Normalization de nomes (employee names)
- Validação de emails (if applicable)
- Type checking em storage layer
- DataStoreError com feedback claro

---

## 📚 Documentação

| Documento | Conteúdo |
|-----------|----------|
| [README.md](README.md) | Guia principal: instalação, uso, features, deployment |
| [DOCKER.md](DOCKER.md) | Guia completo: Docker, docker-compose, PostgreSQL, Nginx |
| [CHANGELOG.md](CHANGELOG.md) | Histórico de versões e melhorias |
| [pyproject.toml](pyproject.toml) | Metadata, dependências, build config |
| [Dockerfile](Dockerfile) | Containerização com Python 3.11 |
| [docker-compose.yml](docker-compose.yml) | Orquestração app + PostgreSQL |

---

## 🚀 Deployment

### Local Development
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e .
streamlit run python_app.py
```

### Docker (Recommended)
```bash
docker-compose up -d
# App available at http://localhost:8501
```

### Production (PostgreSQL)
```bash
export DATABASE_URL=postgresql://user:pass@host:5432/db
streamlit run python_app.py
```

### Streamlit Cloud
1. Push repo to GitHub
2. Deploy via https://share.streamlit.io/
3. Configure secrets: `DATABASE_URL` (optional)

---

## ✅ Checklist de Funcionalidades

- ✅ Calendário interativo para seleção de datas
- ✅ Pedidos de ausência com tipos (Férias, Doença, Compensação, etc.)
- ✅ Aprovação/rejeição de pedidos com audit trail
- ✅ Relatórios em Excel com estatísticas
- ✅ Gestão de staff (CRUD)
- ✅ Gestão de logins com roles
- ✅ Backup/restauro de dados
- ✅ Acessibilidade (sr-only labels, contraste, navegação por teclado)
- ✅ Internationalization (PT/EN com seletor dinâmico)
- ✅ Docker support (Dockerfile + docker-compose)
- ✅ PostgreSQL support (via DATABASE_URL)
- ✅ Audit logging (JSONL format)
- ✅ E2E tests (3 testes passando)
- ✅ Performance optimization (caching, lazy-loading)
- ✅ GitHub Actions CI/CD pipeline
- ✅ Comprehensive documentation

---

## 🔄 Migration from v0.1.0

### Breaking Changes
- None. v0.2.0 é backwards compatible com v0.1.0

### Recommended Updates
1. Rebuild Docker image: `docker build -t marcacao-ferias:v0.2.0 .`
2. Update deployment env var (if using PostgreSQL): `DATABASE_URL=...`
3. Test audit logging: Check `audit_logs/audit.jsonl` after mutations

---

## 🐛 Known Limitations

1. **Streamlit Community Cloud**: Without PostgreSQL, data can be lost on instance recreation
2. **Real-time Sync**: Multi-user edits require page refresh (Streamlit limitation)
3. **Mobile**: Otimizado para desktop e tablets, mobile experience basic
4. **Email Notifications**: Não implementado (roadmap v0.3.0)

---

## 🗺️ Roadmap (v0.3.0+)

- [ ] Integração com Google Calendar
- [ ] Notificações por email
- [ ] Mobile app (React Native)
- [ ] Dashboard de analytics avançado
- [ ] Integração com RH (ADP, Personio, etc.)
- [ ] Aprovação multi-nível (escalation)
- [ ] Substituição automática de cobertura
- [ ] Integração com Slack/Teams

---

## 📞 Support

- **Bugs**: Abra uma issue no [GitHub](https://github.com/e-nmsantos/marcacao-ferias/issues)
- **Sugestões**: Discussões no GitHub
- **Documentação**: Veja README.md, DOCKER.md, e docstrings no código

---

## 📄 Licença

MIT License — veja [LICENSE](LICENSE) para detalhes

---

## 👏 Agradecimentos

Desenvolvido para simplificar a gestão de férias em equipas dinâmicas.

**Versão**: 0.2.0  
**Estado**: ✅ Production Ready  
**Commit**: Veja `git log` para histórico completo
