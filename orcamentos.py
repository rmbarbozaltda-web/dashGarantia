import requests
from requests.adapters import HTTPAdapter, Retry
import pandas as pd
from pandas import json_normalize
import json
import re

# Configurações
API_KEY = "ODU1OWZkODItYjU3MC00NjllLTlmYjEtYTA3ZGJjNzBmN2E2OjU3MDE2"
BASE_URL = "https://carchost.fieldcontrol.com.br/quotations"
HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "X-Api-Key": API_KEY,
}
OFFSET_STEP = 100
TIMEOUT = 30

# Sessão com retry
session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

# Mapeamento de status (inglês -> português) com acréscimos
STATUS_MAP = {
    "draft": "Rascunho",
    "drafted": "Rascunho",
    "draft_only": "Rascunho",
    "sent": "Enviada",
    "sent_to_customer": "Enviada",
    "pending": "Pendente",
    "waiting": "Aguardando",
    "approved": "Aprovada",
    "accepted": "Aprovada",
    "rejected": "Rejeitada",
    "declined": "Rejeitada",
    "refused": "Recusada",
    "refuse": "Recusada",
    "canceled": "Cancelada",
    "cancelled": "Cancelada",
    "open": "Aberta",
    "closed": "Fechada",
    "issued": "Emitida",
    "in_progress": "Em andamento",
    "in-progress": "Em andamento",
    "completed": "Concluída",
    "done": "Concluída",
    "expired": "Expirada",
    "expired_quote": "Expirada",
    "expired_at": "Expirada",
    # outros mapeamentos possíveis
}

def translate_status_value(raw_val):
    """
    Recebe valor de status (str, dict, num) e retorna tradução em pt.
    - Se for dict, tenta extrair campos comuns (name, value, status, label).
    - Normaliza string, extrai tokens alfabéticos e tenta mapear cada token.
    - Se não encontrar mapeamento, retorna a string original com capitalização.
    """
    if raw_val is None:
        return None
    # Trata dicts aninhados
    if isinstance(raw_val, dict):
        for key in ("name", "value", "status", "label"):
            if key in raw_val and isinstance(raw_val[key], (str, int, float)):
                return translate_status_value(raw_val[key])
        # se não achou, converte dict em string e continua
        raw_val = json.dumps(raw_val)
    s = str(raw_val).strip()
    if not s:
        return s
    # Normaliza: remove acentos/pub/ponts e torna lower
    s_norm = s.lower()
    # Remove caracteres não alfanuméricos exceto underline e espaço, substitui por espaço
    s_clean = re.sub(r"[^a-z0-9_ ]+", " ", s_norm)
    # Se houver underscores ou camelCase, transforma em tokens
    tokens = re.split(r"[\s_]+", s_clean)
    # Tenta mapear tokens na ordem (do mais informativo ao menos)
    for tok in tokens:
        if not tok:
            continue
        # direto no mapa
        if tok in STATUS_MAP:
            return STATUS_MAP[tok]
        # tenta sufixos (ex: status:expired -> expired)
        if ":" in tok:
            candidate = tok.split(":")[-1]
            if candidate in STATUS_MAP:
                return STATUS_MAP[candidate]
        # tenta remover prefixos comuns
        for prefix in ("status", "st", "estado"):
            if tok.startswith(prefix):
                candidate = tok[len(prefix):].lstrip("_-:")
                if candidate in STATUS_MAP:
                    return STATUS_MAP[candidate]
    # Se não encontrou, tenta mapear a string inteira com underscores
    s_underscore = s_clean.replace(" ", "_")
    if s_underscore in STATUS_MAP:
        return STATUS_MAP[s_underscore]
    # fallback: capitalize (mantém legibilidade) e retorna original
    return s.capitalize()

def apply_status_translation_df(df):
    """
    Detecta coluna de status e cria:
      - status_original (mantém o valor bruto)
      - status (valor traduzido para pt)
    """
    if df is None or df.empty:
        return df
    # Detecta colunas prováveis contendo status
    possible_cols = [c for c in df.columns if c.lower().endswith("status") or c.lower() == "status" or "status." in c.lower()]
    if not possible_cols:
        for alt in ("state", "situacao"):
            if alt in df.columns:
                possible_cols.append(alt)
    if not possible_cols:
        return df
    # Preferir coluna exatamente 'status' se existir
    chosen_col = None
    for c in possible_cols:
        if c.lower() == "status":
            chosen_col = c
            break
    if chosen_col is None:
        chosen_col = possible_cols[0]
    # Garantir coluna status_original existe (sem sobrescrever se já existir)
    if "status_original" not in df.columns:
        df["status_original"] = df[chosen_col]
    # Criar/atualizar coluna 'status' com tradução
    df["status"] = df[chosen_col].apply(translate_status_value)
    return df

def extract_records_from_response(json_resp):
    if isinstance(json_resp, list):
        return json_resp
    if not isinstance(json_resp, dict):
        return []
    for k in ("data", "items", "rows", "quotations", "results"):
        if k in json_resp and isinstance(json_resp[k], list):
            return json_resp[k]
    for v in json_resp.values():
        if isinstance(v, list):
            return v
    return []

def fetch_all_quotations():
    offset = 0
    all_records = []
    while True:
        params = {"offset": offset, "limit": OFFSET_STEP}
        try:
            resp = session.get(BASE_URL, headers=HEADERS, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise SystemExit(f"Erro de conexão ao chamar a API: {e}")
        if resp.status_code != 200:
            raise SystemExit(f"Erro na requisição: status {resp.status_code}, resposta: {resp.text}")
        try:
            json_resp = resp.json()
        except ValueError:
            raise SystemExit("Resposta da API não é JSON válido.")
        records = extract_records_from_response(json_resp)
        if not records:
            break
        all_records.extend(records)
        if len(records) < OFFSET_STEP:
            break
        offset += OFFSET_STEP
    return all_records

def normalize_items_from_records(records):
    items_expanded = []
    quotations_clean = []
    for rec in records:
        quotation_id = rec.get("id") or (rec.get("quotation") and rec.get("quotation").get("id"))
        raw_items = rec.get("items") if "items" in rec else rec.get("itens") if "itens" in rec else None
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                raw_items = None
        if isinstance(raw_items, list):
            for it in raw_items:
                item_row = {}
                item_row["item_id"] = it.get("id")
                item_row["item_quantity"] = it.get("quantity")
                item_row["item_total"] = try_parse_number(it.get("total"))
                item_row["item_description"] = it.get("description")
                item_row["item_position"] = it.get("position")
                item_row["item_quotation_ref"] = it.get("quotation").get("id") if isinstance(it.get("quotation"), dict) else None
                ps = it.get("productService") or {}
                if isinstance(ps, dict):
                    item_row["productService_id"] = ps.get("id")
                    item_row["productService_value"] = try_parse_number(ps.get("value"))
                    item_row["productService_type"] = ps.get("type")
                else:
                    item_row["productService_id"] = None
                    item_row["productService_value"] = None
                    item_row["productService_type"] = None
                item_row["quotation_id"] = quotation_id
                items_expanded.append(item_row)
        rec_copy = dict(rec)
        if "items" in rec_copy:
            rec_copy.pop("items")
        if "itens" in rec_copy:
            rec_copy.pop("itens")
        quotations_clean.append(rec_copy)
    df_items = pd.DataFrame(items_expanded) if items_expanded else pd.DataFrame(columns=[
        "item_id","item_quantity","item_total","item_description","item_position",
        "item_quotation_ref","productService_id","productService_value","productService_type","quotation_id"
    ])
    df_quotations = json_normalize(quotations_clean) if quotations_clean else pd.DataFrame()
    if not df_quotations.empty and "id" in df_quotations.columns:
        cols = df_quotations.columns.tolist()
        cols.insert(0, cols.pop(cols.index("id")))
        df_quotations = df_quotations[cols]
    # Aplica tradução de status (mantém status_original)
    df_quotations = apply_status_translation_df(df_quotations)
    return df_quotations, df_items

def try_parse_number(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return x
    try:
        s = str(x).replace(".", "").replace(",", ".")
        if "." not in s:
            return int(s)
        return float(s)
    except Exception:
        return x

def save_to_excel_multiple_sheets(df_quotations, df_items, filename="orcamentos.xlsx"):
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        df_quotations.to_excel(writer, sheet_name="quotations", index=False)
        df_items.to_excel(writer, sheet_name="items", index=False)
    print(f"Arquivo salvo: {filename} (quotations: {len(df_quotations)} linhas, items: {len(df_items)} linhas)")

# --- INÍCIO DA CORREÇÃO ---

# 1. A lógica principal foi movida para dentro desta função.
def gerar_arquivo_orcamentos():
    """
    Função principal que busca todos os orçamentos, processa os dados
    e salva o resultado em um arquivo Excel com duas abas.
    """
    print("Iniciando download de quotations com offset de 100...")
    records = fetch_all_quotations()
    print(f"Total de cotações obtidas: {len(records)}")
    df_quotations, df_items = normalize_items_from_records(records)
    save_to_excel_multiple_sheets(df_quotations, df_items)
    print("Concluído.")

# 2. Este bloco agora apenas chama a função principal.
# Isso garante que o script funcione tanto ao ser executado diretamente
# quanto ao ser importado por outro módulo.
if __name__ == "__main__":
    gerar_arquivo_orcamentos()

# --- FIM DA CORREÇÃO ---





