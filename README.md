---
title: OpenProject Task Creator
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: "4.44.0"
python_version: "3.10"
app_file: app.py
pinned: false
---

# OpenProject Task Creator (Hugging Face Spaces + Gradio)

> **Importante:** os metadados acima são obrigatórios no Hugging Face Spaces. Não remova o bloco YAML inicial.

Aplicativo em Python com Gradio para colar um texto livre, extrair informações estruturadas da tarefa e criar um **Work Package** no **OpenProject API v3**.

## Arquitetura (resumo)

- **UI (`gradio`)**: interface dividida em blocos (texto, dados extraídos, projeto/pessoas, datas/prioridade, ações).
- **Camada API OpenProject (`requests`)**:
  - autenticação Basic Auth (`apikey` + `OPENPROJECT_TOKEN`)
  - funções separadas para listar projetos, tipos, prioridades, memberships e criar work package
- **Extração (`heurística + regex`)**:
  - extrai título, descrição, prioridade, percentual, esforço, trabalho restante, assignee sugerido e datas
  - saída sempre em JSON estruturado
- **Validação e logs**:
  - valida campos essenciais antes de enviar
  - mostra logs de sucesso/erro em português

## Estrutura do projeto

```bash
.
├── app.py
├── requirements.txt
└── README.md
```

## Variáveis de ambiente

Defina as variáveis abaixo (localmente ou no Hugging Face Spaces):

- `OPENPROJECT_BASE_URL` (obrigatória)
  - Exemplo: `https://weka.inf.ufes.br/openproject/api/v3`
- `OPENPROJECT_TOKEN` (obrigatória)
  - Token de API do OpenProject
- `OPENPROJECT_DEFAULT_TYPE` (opcional)
  - Padrão: `Task`
- `PORT` (opcional, para execução local)
  - Padrão: `7860`

## Configuração no Hugging Face Spaces

1. Crie um novo Space com SDK **Gradio**.
2. Faça upload dos arquivos (`app.py`, `requirements.txt`, `README.md`).
3. No Space, vá em **Settings > Variables and secrets**.
4. Adicione:
   - `OPENPROJECT_BASE_URL`
   - `OPENPROJECT_TOKEN` (como secret)
   - (opcional) `OPENPROJECT_DEFAULT_TYPE`
5. Reinicie o Space.

## Como executar localmente

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
export OPENPROJECT_BASE_URL="https://SEU_OPENPROJECT/api/v3"
export OPENPROJECT_TOKEN="SEU_TOKEN"
python app.py
```

Acesse: `http://localhost:7860`

## Exemplo de uso

Texto de entrada:

> "Criar uma tarefa para corrigir o problema de login do sistema acadêmico. Prioridade alta. Atribuir para João. Início amanhã e conclusão até sexta."

Fluxo:

1. Clique em **Extrair informações**.
2. Revise/edite os campos extraídos.
3. Selecione o **Projeto**.
4. Aguarde o carregamento automático de membros.
5. Escolha **Atribuído para** / **Responsável** (opcional).
6. Clique em **Criar tarefa no OpenProject**.
7. Verifique o retorno JSON da API e os logs.

## Observações importantes

- Se a extração automática falhar, o formulário continua editável para preenchimento manual.
- Prioridades são buscadas via API (`/priorities`) e não hardcoded.
- O código trata links `href` em formatos comuns como:
  - `/api/v3/...`
  - `/openproject/api/v3/...`
- Alguns campos opcionais (categoria, versão, orçamento, tempos) podem depender de customizações do seu OpenProject.

## Endpoints OpenProject usados

- `GET /projects`
- `GET /types`
- `GET /priorities`
- `GET /memberships` (filtrado por projeto)
- `POST /work_packages`

## Próximo passo (LLM)

A função `extract_task_data` foi implementada com heurística/regex para funcionamento imediato. Ela pode ser substituída por um extrator baseado em LLM mantendo o mesmo JSON de saída.
