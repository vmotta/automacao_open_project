import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("openproject_gradio")

DEFAULT_TYPE_NAME = os.getenv("OPENPROJECT_DEFAULT_TYPE", "Task")
EXTRACTION_TEMPLATE = {
    "titulo": "",
    "descricao": "",
    "prioridade": "",
    "atribuido_nome": "",
    "responsavel_nome": "",
    "data_inicio": "",
    "data_fim": "",
    "percentual_conclusao": 0,
    "trabalho": "",
    "trabalho_restante": "",
    "categoria": "",
    "versao": "",
    "orcamento": "",
}


@dataclass
class OpenProjectConfig:
    base_url: str
    token: str


def get_config() -> OpenProjectConfig:
    base_url = os.getenv("OPENPROJECT_BASE_URL", "").strip().rstrip("/")
    token = os.getenv("OPENPROJECT_TOKEN", "").strip()
    if not base_url:
        raise ValueError("A variável OPENPROJECT_BASE_URL não está definida.")
    if not token:
        raise ValueError("A variável OPENPROJECT_TOKEN não está definida.")
    return OpenProjectConfig(base_url=base_url, token=token)


def resolve_href(base_url: str, href: str) -> str:
    href = href.strip()
    if href.startswith("http"):
        return href
    origin = base_url.split("/api/v3")[0]
    if href.startswith("/openproject/api/v3"):
        return f"{origin}{href}"
    if href.startswith("/api/v3"):
        return f"{origin}{href}"
    if href.startswith("/"):
        return f"{origin}{href}"
    return f"{base_url}/{href.lstrip('/')}"


def _request(
    method: str,
    endpoint_or_href: str,
    config: OpenProjectConfig,
    params: Optional[Dict[str, Any]] = None,
    json_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = (
        resolve_href(config.base_url, endpoint_or_href)
        if endpoint_or_href.startswith("/") or endpoint_or_href.startswith("http")
        else f"{config.base_url}/{endpoint_or_href.lstrip('/')}"
    )

    logger.info("%s %s", method.upper(), url)
    response = requests.request(
        method=method.upper(),
        url=url,
        auth=HTTPBasicAuth("apikey", config.token),
        headers={"Content-Type": "application/json"},
        params=params,
        json=json_payload,
        timeout=30,
    )

    if response.status_code >= 400:
        raise RuntimeError(format_api_error(response))

    if not response.text.strip():
        return {}
    return response.json()


def format_api_error(response: requests.Response) -> str:
    status = f"HTTP {response.status_code}"
    try:
        body = response.json()
        message = body.get("message") or body.get("error") or json.dumps(body, ensure_ascii=False)
    except Exception:
        message = response.text[:600]
    return f"Erro na API OpenProject ({status}): {message}"


def list_projects(config: OpenProjectConfig) -> List[Dict[str, Any]]:
    data = _request("GET", "projects", config)
    return data.get("_embedded", {}).get("elements", [])


def list_types(config: OpenProjectConfig) -> List[Dict[str, Any]]:
    data = _request("GET", "types", config)
    return data.get("_embedded", {}).get("elements", [])


def list_priorities(config: OpenProjectConfig) -> List[Dict[str, Any]]:
    data = _request("GET", "priorities", config)
    return data.get("_embedded", {}).get("elements", [])


def list_project_memberships(config: OpenProjectConfig, project_id: int) -> List[Dict[str, Any]]:
    data = _request("GET", f"memberships?filters=[{{\"project\":{{\"operator\":\"=\",\"values\":[\"{project_id}\"]}}}}]", config)
    return data.get("_embedded", {}).get("elements", [])


def extract_member_users(memberships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    users: Dict[int, Dict[str, Any]] = {}
    for m in memberships:
        principal = m.get("_links", {}).get("principal", {})
        href = principal.get("href", "")
        title = principal.get("title", "")
        id_match = re.search(r"/users/(\d+)", href)
        if not id_match:
            continue
        uid = int(id_match.group(1))
        users[uid] = {"id": uid, "name": title or f"Usuário {uid}", "href": href}
    return sorted(users.values(), key=lambda x: x["name"].lower())


def create_work_package(config: OpenProjectConfig, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _request("POST", "work_packages", config, json_payload=payload)


def parse_date_pt(text: str) -> Optional[str]:
    text_low = text.lower()
    today = date.today()
    week_days = {
        "segunda": 0,
        "terça": 1,
        "terca": 1,
        "quarta": 2,
        "quinta": 3,
        "sexta": 4,
        "sábado": 5,
        "sabado": 5,
        "domingo": 6,
    }

    if "hoje" in text_low:
        return today.isoformat()
    if "amanhã" in text_low or "amanha" in text_low:
        return (today + timedelta(days=1)).isoformat()

    for key, wd in week_days.items():
        if key in text_low:
            days_ahead = (wd - today.weekday()) % 7
            days_ahead = 7 if days_ahead == 0 else days_ahead
            return (today + timedelta(days=days_ahead)).isoformat()

    match_iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if match_iso:
        return match_iso.group(1)

    match_br = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text)
    if match_br:
        d, m, y = match_br.groups()
        y = f"20{y}" if len(y) == 2 else y
        try:
            return datetime(int(y), int(m), int(d)).date().isoformat()
        except ValueError:
            return None

    return None


def extract_task_data(text: str) -> Dict[str, Any]:
    result = dict(EXTRACTION_TEMPLATE)
    clean_text = text.strip()
    if not clean_text:
        return result

    sentences = [s.strip() for s in re.split(r"[\n\.!?]+", clean_text) if s.strip()]
    result["descricao"] = clean_text
    result["titulo"] = sentences[0][:120] if sentences else ""

    prio_match = re.search(r"prioridade\s*[:\-]?\s*(alta|m[eé]dia|media|baixa|urgente)", clean_text, flags=re.IGNORECASE)
    if prio_match:
        p = prio_match.group(1).lower()
        result["prioridade"] = "Média" if p in {"média", "media"} else p.capitalize()

    pct_match = re.search(r"(\d{1,3})\s*%", clean_text)
    if pct_match:
        result["percentual_conclusao"] = min(100, int(pct_match.group(1)))

    assignee_match = re.search(r"(?:atribuir\s+para|atribu[ií]do\s+para|respons[áa]vel\s*[:\-]?)\s+([\wÀ-ÿ ]{2,50})", clean_text, flags=re.IGNORECASE)
    if assignee_match:
        name = assignee_match.group(1).strip(" .,")
        result["atribuido_nome"] = name

    work_match = re.search(r"(?:trabalho|esfor[cç]o|estimativa)\s*[:\-]?\s*([\d\.,]+\s*(?:h|hora|horas|dia|dias))", clean_text, flags=re.IGNORECASE)
    if work_match:
        result["trabalho"] = work_match.group(1)

    remaining_match = re.search(r"trabalho\s+restante\s*[:\-]?\s*([\d\.,]+\s*(?:h|hora|horas|dia|dias))", clean_text, flags=re.IGNORECASE)
    if remaining_match:
        result["trabalho_restante"] = remaining_match.group(1)

    ini_match = re.search(r"(?:in[ií]cio|come[cç]a|iniciar)\s*(?:em|:)?\s*([^\.,\n]+)", clean_text, flags=re.IGNORECASE)
    fim_match = re.search(r"(?:fim|conclus[aã]o|entrega|at[eé])\s*(?:em|:)?\s*([^\.,\n]+)", clean_text, flags=re.IGNORECASE)

    if ini_match:
        result["data_inicio"] = parse_date_pt(ini_match.group(1)) or ""
    if fim_match:
        result["data_fim"] = parse_date_pt(fim_match.group(1)) or ""

    return result


def project_choices(projects: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, int]]:
    mapping: Dict[str, int] = {}
    labels: List[str] = []
    for p in projects:
        pid = p.get("id")
        name = p.get("name", f"Projeto {pid}")
        label = f"{name} (ID: {pid})"
        labels.append(label)
        mapping[label] = pid
    return labels, mapping


def user_choices(users: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, int]]:
    mapping: Dict[str, int] = {}
    labels: List[str] = ["(Não definido)"]
    mapping["(Não definido)"] = 0
    for u in users:
        label = f"{u['name']} (ID: {u['id']})"
        labels.append(label)
        mapping[label] = u["id"]
    return labels, mapping


def map_priority_name_to_href(priorities: List[Dict[str, Any]], name: str) -> Optional[str]:
    if not name:
        return None
    for p in priorities:
        if p.get("name", "").strip().lower() == name.strip().lower():
            return p.get("_links", {}).get("self", {}).get("href")
    for p in priorities:
        if name.strip().lower() in p.get("name", "").strip().lower():
            return p.get("_links", {}).get("self", {}).get("href")
    return None


def get_type_href_by_name(types: List[Dict[str, Any]], target_name: str) -> Optional[str]:
    for t in types:
        if t.get("name", "").strip().lower() == target_name.strip().lower():
            return t.get("_links", {}).get("self", {}).get("href")
    return types[0].get("_links", {}).get("self", {}).get("href") if types else None


def build_payload(
    title: str,
    description: str,
    project_id: int,
    type_href: str,
    priority_href: Optional[str],
    assignee_id: Optional[int],
    responsible_id: Optional[int],
    start_date: str,
    due_date: str,
    percent_complete: int,
    work: str,
    work_remaining: str,
    category: str,
    version: str,
    budget: str,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subject": title.strip(),
        "description": {"format": "markdown", "raw": description.strip() or title.strip()},
        "_links": {
            "project": {"href": f"/api/v3/projects/{project_id}"},
            "type": {"href": type_href},
        },
        "percentageDone": max(0, min(100, int(percent_complete or 0))),
    }

    if priority_href:
        payload["_links"]["priority"] = {"href": priority_href}
    if assignee_id and assignee_id > 0:
        payload["_links"]["assignee"] = {"href": f"/api/v3/users/{assignee_id}"}
    if responsible_id and responsible_id > 0:
        payload["_links"]["responsible"] = {"href": f"/api/v3/users/{responsible_id}"}
    if start_date:
        payload["startDate"] = start_date
    if due_date:
        payload["dueDate"] = due_date

    # Campos adicionais opcionais para manter no payload e facilitar evolução futura
    if work:
        payload["estimatedTime"] = work
    if work_remaining:
        payload["remainingTime"] = work_remaining
    if category:
        payload["category"] = category
    if version:
        payload["version"] = version
    if budget:
        payload["budget"] = budget

    return payload


def validate_before_create(title: str, project_label: str, type_href: Optional[str]) -> Optional[str]:
    if not title.strip():
        return "O título é obrigatório."
    if not project_label.strip():
        return "Selecione um projeto."
    if not type_href:
        return "Não foi possível encontrar o tipo da tarefa (Task)."
    return None


def load_initial_data() -> Tuple[List[str], Dict[str, Any], str]:
    try:
        config = get_config()
        projects = list_projects(config)
        types = list_types(config)
        priorities = list_priorities(config)

        proj_labels, proj_map = project_choices(projects)
        priority_names = ["(Não definido)"] + [p.get("name", "") for p in priorities if p.get("name")]

        state = {
            "projects_map": proj_map,
            "types": types,
            "priorities": priorities,
            "users_map": {"(Não definido)": 0},
            "members": [],
            "priority_names": priority_names,
        }
        msg = f"Dados carregados com sucesso. Projetos: {len(projects)} | Tipos: {len(types)} | Prioridades: {len(priorities)}"
        return proj_labels, state, msg
    except Exception as e:
        logger.exception("Falha ao carregar dados iniciais")
        return [], {
            "projects_map": {}, "types": [], "priorities": [], "users_map": {"(Não definido)": 0}, "members": [], "priority_names": ["(Não definido)"]
        }, f"Erro ao carregar dados iniciais: {e}"


def on_project_change(project_label: str, state: Dict[str, Any]):
    logs = []
    try:
        pid = state.get("projects_map", {}).get(project_label)
        if not pid:
            logs.append("Selecione um projeto válido.")
            choices = ["(Não definido)"]
            return gr.update(choices=choices, value="(Não definido)"), gr.update(choices=choices, value="(Não definido)"), state, "\n".join(logs)

        config = get_config()
        memberships = list_project_memberships(config, pid)
        members = extract_member_users(memberships)
        labels, mapping = user_choices(members)
        state["users_map"] = mapping
        state["members"] = members
        logs.append(f"Membros carregados para o projeto {project_label}: {len(members)}")
        return gr.update(choices=labels, value="(Não definido)"), gr.update(choices=labels, value="(Não definido)"), state, "\n".join(logs)
    except Exception as e:
        logger.exception("Erro ao carregar membros")
        logs.append(f"Erro ao carregar membros do projeto: {e}")
        choices = ["(Não definido)"]
        return gr.update(choices=choices, value="(Não definido)"), gr.update(choices=choices, value="(Não definido)"), state, "\n".join(logs)


def on_extract(text: str, state: Dict[str, Any]):
    logs = []
    try:
        data = extract_task_data(text)
        logs.append("Extração concluída com heurística/regex.")

        selected_priority = data.get("prioridade", "")
        valid_priorities = state.get("priority_names", ["(Não definido)"])
        if selected_priority and selected_priority not in valid_priorities:
            selected_priority = "(Não definido)"
        if not selected_priority:
            selected_priority = "(Não definido)"

        extracted_json = json.dumps(data, ensure_ascii=False, indent=2)
        return (
            data.get("titulo", ""),
            data.get("descricao", ""),
            data.get("data_inicio", ""),
            data.get("data_fim", ""),
            int(data.get("percentual_conclusao", 0) or 0),
            selected_priority,
            data.get("trabalho", ""),
            data.get("trabalho_restante", ""),
            data.get("categoria", ""),
            data.get("versao", ""),
            data.get("orcamento", ""),
            extracted_json,
            "\n".join(logs),
        )
    except Exception as e:
        logger.exception("Erro na extração")
        logs.append(f"Erro na extração: {e}")
        return "", "", "", "", 0, "(Não definido)", "", "", "", "", "", json.dumps(EXTRACTION_TEMPLATE, ensure_ascii=False, indent=2), "\n".join(logs)


def on_create(
    title: str,
    description: str,
    project_label: str,
    assignee_label: str,
    responsible_label: str,
    start_date: str,
    due_date: str,
    priority_name: str,
    percent_complete: int,
    work: str,
    work_remaining: str,
    category: str,
    version: str,
    budget: str,
    state: Dict[str, Any],
):
    logs: List[str] = []
    try:
        config = get_config()
        project_id = state.get("projects_map", {}).get(project_label)
        type_href = get_type_href_by_name(state.get("types", []), DEFAULT_TYPE_NAME)
        validation_error = validate_before_create(title, project_label, type_href)
        if validation_error:
            return "", f"❌ {validation_error}"

        priority_href = None
        if priority_name and priority_name != "(Não definido)":
            priority_href = map_priority_name_to_href(state.get("priorities", []), priority_name)
            if not priority_href:
                logs.append(f"Prioridade '{priority_name}' não encontrada por nome exato; tarefa seguirá sem prioridade explícita.")

        assignee_id = state.get("users_map", {}).get(assignee_label, 0)
        responsible_id = state.get("users_map", {}).get(responsible_label, 0)

        payload = build_payload(
            title=title,
            description=description,
            project_id=project_id,
            type_href=type_href,
            priority_href=priority_href,
            assignee_id=assignee_id,
            responsible_id=responsible_id,
            start_date=start_date,
            due_date=due_date,
            percent_complete=percent_complete,
            work=work,
            work_remaining=work_remaining,
            category=category,
            version=version,
            budget=budget,
        )

        logs.append("Payload montado com sucesso.")
        response = create_work_package(config, payload)
        wp_id = response.get("id")
        wp_subject = response.get("subject")
        wp_href = response.get("_links", {}).get("self", {}).get("href", "")

        logs.append(f"Work package criado com sucesso: ID={wp_id} | Título={wp_subject}")
        logs.append(f"Link API: {wp_href}")

        return json.dumps(response, ensure_ascii=False, indent=2), "✅ " + "\n".join(logs)
    except Exception as e:
        logger.exception("Erro ao criar work package")
        logs.append(f"Erro ao criar tarefa: {e}")
        return "", "❌ " + "\n".join(logs)


def build_app() -> gr.Blocks:
    projects, state, boot_log = load_initial_data()
    priority_choices = state.get("priority_names", ["(Não definido)"])

    with gr.Blocks(title="OpenProject - Criador de Tarefas") as app:
        gr.Markdown("# OpenProject - Criador de Tarefas (HF Spaces + Gradio)")
        gr.Markdown(
            "Cole um texto em linguagem natural, extraia dados automaticamente, revise os campos e crie a tarefa no OpenProject."
        )

        state_holder = gr.State(state)

        with gr.Group():
            gr.Markdown("## 1) Texto de entrada")
            text_input = gr.Textbox(
                label="Descrição livre da tarefa",
                lines=8,
                placeholder="Ex.: Corrigir bug de login. Prioridade alta. Atribuir para João. Início amanhã e concluir até sexta.",
            )
            btn_extract = gr.Button("Extrair informações", variant="primary")

        with gr.Group():
            gr.Markdown("## 2) Dados extraídos (editáveis)")
            title = gr.Textbox(label="Título")
            description = gr.Textbox(label="Descrição", lines=4)
            extracted_json = gr.Code(label="JSON extraído", language="json", value=json.dumps(EXTRACTION_TEMPLATE, ensure_ascii=False, indent=2))

            with gr.Row():
                work = gr.Textbox(label="Trabalho (estimado)", placeholder="Ex.: 8h")
                work_remaining = gr.Textbox(label="Trabalho restante", placeholder="Ex.: 4h")

            with gr.Row():
                category = gr.Textbox(label="Categoria")
                version = gr.Textbox(label="Versão")
                budget = gr.Textbox(label="Orçamento")

        with gr.Group():
            gr.Markdown("## 3) Projeto e pessoas")
            project = gr.Dropdown(label="Projeto", choices=projects, value=projects[0] if projects else None)
            assignee = gr.Dropdown(label="Atribuído para", choices=["(Não definido)"], value="(Não definido)")
            responsible = gr.Dropdown(label="Responsável (opcional)", choices=["(Não definido)"], value="(Não definido)")

        with gr.Group():
            gr.Markdown("## 4) Datas e prioridade")
            with gr.Row():
                start_date = gr.Textbox(label="Data de início (YYYY-MM-DD)", placeholder="2026-04-15")
                due_date = gr.Textbox(label="Data de conclusão (YYYY-MM-DD)", placeholder="2026-04-18")

            with gr.Row():
                priority = gr.Dropdown(label="Prioridade", choices=priority_choices, value="(Não definido)")
                percent = gr.Slider(label="% de conclusão", minimum=0, maximum=100, value=0, step=1)

        with gr.Group():
            gr.Markdown("## 5) Ações")
            btn_create = gr.Button("Criar tarefa no OpenProject", variant="primary")
            logs = gr.Textbox(label="Logs / Erros / Sucesso", lines=8, value=boot_log)
            create_response = gr.Code(label="Resposta da API", language="json")

        project.change(
            fn=on_project_change,
            inputs=[project, state_holder],
            outputs=[assignee, responsible, state_holder, logs],
        )

        btn_extract.click(
            fn=on_extract,
            inputs=[text_input, state_holder],
            outputs=[
                title,
                description,
                start_date,
                due_date,
                percent,
                priority,
                work,
                work_remaining,
                category,
                version,
                budget,
                extracted_json,
                logs,
            ],
        )

        btn_create.click(
            fn=on_create,
            inputs=[
                title,
                description,
                project,
                assignee,
                responsible,
                start_date,
                due_date,
                priority,
                percent,
                work,
                work_remaining,
                category,
                version,
                budget,
                state_holder,
            ],
            outputs=[create_response, logs],
        )

    return app


if __name__ == "__main__":
    demo = build_app()
    demo.queue().launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
