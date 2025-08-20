import requests
import pandas as pd
from tqdm import tqdm
import os

API_URL_ORDERS = "https://carchost.fieldcontrol.com.br/orders"
API_URL_SERVICE = "https://carchost.fieldcontrol.com.br/services/"
API_URL_CUSTOMER = "https://carchost.fieldcontrol.com.br/customers/"
API_KEY = "ODU1OWZkODItYjU3MC00NjllLTlmYjEtYTA3ZGJjNzBmN2E2OjU3MDE2"
LIMIT = 100
EXCEL_CAMINHO = "ordens_de_servico.xlsx"
headers = {
    "Content-Type": "application/json;charset=UTF-8",
    "X-Api-Key": API_KEY,
}

def get_all_orders_basic():
    all_orders = []
    offset = 0
    while True:
        params = {"limit": LIMIT, "offset": offset}
        resp = requests.get(API_URL_ORDERS, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"Erro na API de ordens (status {resp.status_code})")
            break
        page = resp.json().get("items", [])
        if not page:
            break
        for item in page:
            all_orders.append({
                "id": item.get("id"),
                "Atualizado em (UTC)": item.get("updatedAt"),
                "archived": item.get("archived"),
            })
        offset += LIMIT
        if len(page) < LIMIT:
            break
    return all_orders

def get_order_detail(order_id):
    url = f"{API_URL_ORDERS}/{order_id}"
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return None
    return resp.json()

def get_service_name(service_id, cache):
    if not service_id:
        return None
    if service_id in cache:
        return cache[service_id]
    resp = requests.get(API_URL_SERVICE + str(service_id), headers=headers)
    if resp.status_code == 200:
        nome = resp.json().get("name")
        cache[service_id] = nome
        return nome
    cache[service_id] = None
    return None

def get_customer_info(customer_id, cache):
    if not customer_id:
        return {}
    if customer_id in cache:
        return cache[customer_id]
    resp = requests.get(API_URL_CUSTOMER + str(customer_id), headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        contato = data.get("contact", {})
        address = data.get("address", {})
        infos = {
            "Cliente": data.get("name"),
            "E-mail Cliente": contato.get("email"),
            "Contato Cliente": contato.get("phone"),
            "Cliente - CEP": address.get("zipCode"),
            "Cliente - Rua": address.get("street"),
            "Cliente - Número": address.get("number"),
            "Cliente - Bairro": address.get("neighborhood"),
            "Cliente - Complemento": address.get("complement"),
            "Cliente - Município": address.get("city"),
            "Cliente - Estado": address.get("state"),
        }
        cache[customer_id] = infos
        return infos
    cache[customer_id] = {}
    return {}

# Nova função para obter etiquetas de uma ordem de serviço
def get_order_labels(order_id):
    url = f"{API_URL_ORDERS}/{order_id}/labels"
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        labels = resp.json().get("items", [])
        return ', '.join(label['name'] for label in labels)  # Juntar os nomes das etiquetas
    return None

def normaliza_data(dt):
    if dt is None:
        return pd.NaT
    out = pd.to_datetime(dt, errors="coerce", utc=True)
    if pd.isna(out):
        return pd.NaT
    if isinstance(out, pd.Timestamp):
        out = out.floor("s")
        return out
    return out

def gerar_arquivo_ordens():
    print("==== BUSCANDO TODAS AS ORDENS (incremental de verdade) ====")
    # Carrega base antiga (caso exista)
    if os.path.exists(EXCEL_CAMINHO):
        df_antigo = pd.read_excel(EXCEL_CAMINHO, dtype=str)
        print(f"Base antiga carregada: {len(df_antigo)} OS registradas.")
        if "Atualizado em (UTC)" in df_antigo.columns:
            df_antigo["Atualizado em (UTC)"] = pd.to_datetime(df_antigo["Atualizado em (UTC)"], errors="coerce", utc=True).dt.floor("s")
        if "Criado em (UTC)" in df_antigo.columns:
            df_antigo["Criado em (UTC)"] = pd.to_datetime(df_antigo["Criado em (UTC)"], errors="coerce", utc=True).dt.floor("s")
        if "id" in df_antigo.columns and df_antigo.index.name != "id":
            df_antigo = df_antigo.set_index("id", drop=False)
    else:
        df_antigo = pd.DataFrame()
        print("Nenhum arquivo antigo encontrado.")
    
    # Consulta todas as OS básicas na API
    all_orders_basic = get_all_orders_basic()
    print(f"Total de OS na API: {len(all_orders_basic)}")
    set_antigo = set(df_antigo["id"]) if not df_antigo.empty else set()
    ordens_a_atualizar = []
    print("\nComparando datas para as primeiras 10 OS encontradas (DEBUG):")
    
    for i, o in enumerate(all_orders_basic):
        id_os = o["id"]
        datapi = normaliza_data(o.get("Atualizado em (UTC)"))
        archived = o.get("archived")
        dataant = None
        if id_os in set_antigo:
            try:
                dataant = normaliza_data(df_antigo.loc[id_os, "Atualizado em (UTC)"])
            except Exception:
                dataant = pd.NaT
        if i < 10:
            print(f'ID: {id_os} | excel: {dataant} | api: {datapi} | igual? {dataant == datapi}')
        
        # Atualiza se não existe, se está diferente ou se está arquivada
        if id_os not in set_antigo:
            ordens_a_atualizar.append(id_os)
        elif archived == "True" or archived is True:
            ordens_a_atualizar.append(id_os)
        elif not pd.isna(datapi):
            if pd.isna(dataant) or dataant != datapi:
                ordens_a_atualizar.append(id_os)

    print(f"\nPrecisam ser atualizadas/baixadas: {len(ordens_a_atualizar)} OS\n")

    # Busca detalhes das OS a atualizar
    linhas = []
    service_cache = {}
    customer_cache = {}
    
    for order_id in tqdm(ordens_a_atualizar, desc="Buscando detalhes incrementais"):
        os_info = get_order_detail(order_id)
        if not os_info:
            continue
        
        linha = {
            "id": os_info.get("id"),
            "Numero OS": os_info.get("identifier"),
            "Criado em (UTC)": os_info.get("createdAt"),
            "Atualizado em (UTC)": os_info.get("updatedAt"),
            "archived": os_info.get("archived"),
            "Descrição": os_info.get("description"),
            "link": os_info.get("link"),
            "Etiquetas": get_order_labels(order_id)  # Obtendo as etiquetas
        }
        
        service_id = os_info.get("service", {}).get("id") if os_info.get("service") else None
        linha["Tipo de Serviço"] = get_service_name(service_id, service_cache)
        customer_id = os_info.get("customer", {}).get("id") if os_info.get("customer") else None
        cliente_info = get_customer_info(customer_id, customer_cache)
        linha.update(cliente_info)
        linhas.append(linha)

    df_novas = pd.DataFrame(linhas)
    for col in ["Criado em (UTC)", "Atualizado em (UTC)"]:
        if col in df_novas.columns:
            df_novas[col] = pd.to_datetime(df_novas[col], errors="coerce", utc=True).dt.floor('s')
    
    if "Atualizado em (UTC)" in df_novas.columns and "Criado em (UTC)" in df_novas.columns:
        mask = df_novas["Atualizado em (UTC)"].isna()
        df_novas.loc[mask, "Atualizado em (UTC)"] = df_novas.loc[mask, "Criado em (UTC)"]
    
    # cria coluna "Atualizado em (Brasília)"
    if "Atualizado em (UTC)" in df_novas.columns:
        df_novas["Atualizado em (Brasília)"] = df_novas["Atualizado em (UTC)"].dt.tz_convert("America/Sao_Paulo")
    
    # --- INCREMENTAL ROBUSTO ---
    if not df_antigo.empty and df_antigo.index.name != "id":
        df_antigo = df_antigo.set_index("id", drop=False)
    ids_para_manter = set(df_antigo.index) - set(ordens_a_atualizar) if not df_antigo.empty else set()
    df_mantidas = df_antigo.loc[list(ids_para_manter)].copy() if not df_antigo.empty and ids_para_manter else pd.DataFrame()
    df_final = pd.concat([df_mantidas, df_novas], ignore_index=True)
    df_final = df_final.drop_duplicates(subset="id", keep="last")
    df_final = df_final.sort_values("Criado em (UTC)", ascending=False)
    
    if "link" not in df_final.columns:
        df_final["link"] = ""
    
    # CORREÇÃO FINAL DE DATETIMES E FUSOS
    for col in ["Criado em (UTC)", "Atualizado em (UTC)", "Atualizado em (Brasília)"]:
        if col in df_final.columns:
            df_final[col] = pd.to_datetime(df_final[col], errors="coerce", utc=True)
            if col == "Atualizado em (Brasília)":
                try:
                    df_final[col] = df_final[col].dt.tz_convert("America/Sao_Paulo")
                except Exception:
                    pass
            if pd.api.types.is_datetime64_any_dtype(df_final[col]):
                try:
                    df_final[col] = df_final[col].dt.tz_localize(None)
                except (TypeError, AttributeError):
                    pass
    
    df_final.to_excel(EXCEL_CAMINHO, index=False)
    print(f"Salvo: {EXCEL_CAMINHO} ({len(df_final)} linhas)")

if __name__ == "__main__":
    gerar_arquivo_ordens()






































