import requests
import pandas as pd
import os
import pytz
from dateutil import parser

API_URL_TASKS = "https://carchost.fieldcontrol.com.br/tasks"
API_URL_EMPLOYEES = "https://carchost.fieldcontrol.com.br/employees/"
API_KEY = "ODU1OWZkODItYjU3MC00NjllLTlmYjEtYTA3ZGJjNzBmN2E2OjU3MDE2"
LIMIT = 100
ARQUIVO = "atividades.xlsx"

headers = {
    "Content-Type": "application/json;charset=UTF-8",
    "X-Api-Key": API_KEY,
}

status_traducao = {
    "done": "Concluída",
    "scheduled": "Agendada",
    "canceled": "Cancelada",
    "reported": "Reportada",
    "pending": "Pendente",
    "in-progress": "Em andamento",
    "on-route": "A caminho"
}

def traduz_status(status, status_nao_traduzidos):
    if pd.notnull(status):
        if status not in status_traducao:
            status_nao_traduzidos.add(status)
        return status_traducao.get(status, status)
    return status

def processa_traducao_status(df):
    status_nao_traduzidos = set()
    if 'status' in df.columns:
        df['status_pt'] = df['status'].apply(lambda x: traduz_status(x, status_nao_traduzidos))
        if status_nao_traduzidos:
            print("ATENÇÃO: Encontrados status sem tradução:")
            for st in status_nao_traduzidos:
                print(f"  - '{st}'")
            print("Adicione ao dicionário 'status_traducao' acima para traduzir corretamente.")
    else:
        print("Aviso: coluna 'status' não encontrada na base.")

def normaliza_colunas_id(df):
    for col in df.columns:
        amostra = df[col].head(10).dropna()
        encontrou_dict = amostra.apply(lambda x: isinstance(x, dict) and 'id' in x if not pd.isnull(x) else False).any()
        if encontrou_dict:
            print(f"Normalizando coluna '{col}' (pegando só o valor de 'id').")
            df[col] = df[col].apply(lambda x: x['id'] if isinstance(x, dict) and 'id' in x else x)

def normaliza_colunas_data_hora(df):
    colunas = df.columns[16:21]  # Q-U
    for col in colunas:
        amostra = df[col].head(10).dropna()
        encontrou_dict = amostra.apply(lambda x: isinstance(x, dict) and ('date' in x or 'time' in x) if not pd.isnull(x) else False).any()
        if encontrou_dict:
            print(f"Normalizando coluna '{col}' (montando string a partir de 'date' e 'time').")
            def dict_to_str(x):
                if not isinstance(x, dict):
                    return x
                dt = x.get('date', '')
                tm = x.get('time', '')
                if dt and tm:
                    return f"{dt} {tm}"
                elif dt:
                    return dt
                elif tm:
                    return tm
                else:
                    return ''
            df[col] = df[col].apply(dict_to_str)

def normaliza_colunas_latlong(df):
    colunas = df.columns[17:21]   # R-U
    for col in colunas:
        amostra = df[col].head(10).dropna()
        encontrou = amostra.apply(
            lambda x:
                (isinstance(x, dict) and
                 (('latitude' in x and 'longitude' in x) or ('coords' in x and isinstance(x['coords'], dict)))
                ) if not pd.isnull(x) else False
        ).any()
        if encontrou:
            print(f"Normalizando coluna '{col}' (latitude/longitude).")
            def extrai_latlong(x):
                if isinstance(x, dict) and 'coords' in x and isinstance(x['coords'], dict):
                    lat = x['coords'].get('latitude')
                    lon = x['coords'].get('longitude')
                elif isinstance(x, dict) and 'latitude' in x and 'longitude' in x:
                    lat = x.get('latitude')
                    lon = x.get('longitude')
                else:
                    return ''
                if lat is None or lon is None:
                    return ''
                return f"{lat}, {lon}"
            df[col] = df[col].apply(extrai_latlong)

def normaliza_datas_para_brasilia(df):
    tz_brasilia = pytz.timezone('America/Sao_Paulo')
    for col in df.columns:
        def formata_data(celula):
            if pd.isnull(celula) or not isinstance(celula, (str, pd.Timestamp)):
                return celula
            try:
                dt = parser.parse(str(celula))
                if dt.tzinfo is None:
                    dt = pytz.utc.localize(dt)
                dt_brasilia = dt.astimezone(tz_brasilia)
                return dt_brasilia.strftime('%d/%m/%Y %H:%M:%S')
            except Exception:
                return celula
        amostra = df[col].head(10).dropna()
        if amostra.apply(lambda x: isinstance(x, (str, pd.Timestamp)) and
                                   '1970' not in str(x) and
                                   any(ch.isdigit() for ch in str(x))
                        ).any():
            qtd_convertidos = amostra.apply(lambda x: False if pd.isnull(x) else True if str(x).strip() == '' else
                                    True if ('-' in str(x) or '/' in str(x)) and any(ch.isdigit() for ch in str(x))
                                    else False
                                   ).sum()
            if qtd_convertidos > 0:
                print(f"Tentando normalizar datas na coluna: '{col}'")
                df[col] = df[col].apply(formata_data)

def get_all_tasks():
    all_data = []
    offset = 0
    while True:
        params = {"limit": LIMIT, "offset": offset}
        resp = requests.get(API_URL_TASKS, headers=headers, params=params)
        if resp.status_code != 200:
            print("Falha ao obter dados:", resp.status_code)
            break
        items = resp.json().get("items", [])
        if not items:
            break
        all_data.extend(items)
        print(f"Obtidas {len(items)} linhas (offset {offset})")
        if len(items) < LIMIT:
            break
        offset += LIMIT
    return all_data

def get_employees():
    employees = []
    offset = 0
    while True:
        params = {"limit": LIMIT, "offset": offset}
        resp = requests.get(
            API_URL_EMPLOYEES, headers=headers, params=params
        )
        if resp.status_code != 200:
            print("Falha ao obter employees:", resp.status_code)
            break
        items = resp.json().get("items", [])
        if not items:
            break
        employees.extend(items)
        if len(items) < LIMIT:
            break
        offset += LIMIT
    id_to_nome = {}
    for emp in employees:
        nome = emp.get("name") or emp.get("fullName") or "Desconhecido"
        _id = emp.get("id") or emp.get("_id")
        if _id:
            id_to_nome[_id] = nome
    return id_to_nome

def adiciona_colaborador_nome(df, id_to_nome):
    col = "employee"
    if col not in df.columns:
        print("Campo 'employee' não encontrado!")
        df["colaborador_nome"] = ""
        return

    print(f"Buscando colaborador pelo campo '{col}'.")
    def obter_id(celula):
        if isinstance(celula, str):
            return celula
        if isinstance(celula, dict):
            return celula.get("id") or celula.get("_id")
        return None

    df["colaborador_nome"] = df[col].apply(lambda x: id_to_nome.get(obter_id(x), 'Não encontrado'))

def gerar_arquivo_atividades():
    id_to_nome = get_employees()

    if not os.path.exists(ARQUIVO):
        print("Arquivo não existe. Gerando base nova de atividades...")
        atividades = get_all_tasks()
        if not atividades:
            print("Nenhuma atividade encontrada.")
            return
        df = pd.DataFrame(atividades)
        normaliza_colunas_id(df)
        normaliza_colunas_data_hora(df)
        normaliza_colunas_latlong(df)
        normaliza_datas_para_brasilia(df)
        processa_traducao_status(df)
        adiciona_colaborador_nome(df, id_to_nome)
        df.to_excel(ARQUIVO, index=False)
        print(f"Base de atividades salva em {ARQUIVO}")
        return

    print("Arquivo já existe. Verificando atualizações...")
    df_antigo = pd.read_excel(ARQUIVO)
    atividades_novas = get_all_tasks()
    if not atividades_novas:
        print("Nenhuma atividade carregada da API.")
        return

    df_novo = pd.DataFrame(atividades_novas)
    if 'id' not in df_antigo.columns or 'id' not in df_novo.columns:
        print("Coluna 'id' não encontrada na base. Verifique a estrutura dos dados.")
        return

    df_antigo.set_index('id', inplace=True)
    df_novo.set_index('id', inplace=True)
    atualizados = 0
    inseridos = 0

    for id_, row in df_novo.iterrows():
        if id_ in df_antigo.index:
            updated_old = str(df_antigo.loc[id_].get('updatedAt', ''))
            updated_new = str(row.get('updatedAt', ''))
            if updated_new != updated_old:
                df_antigo.loc[id_] = row
                atualizados += 1
        else:
            df_antigo.loc[id_] = row
            inseridos += 1

    df_antigo.reset_index(inplace=True)
    normaliza_colunas_id(df_antigo)
    normaliza_colunas_data_hora(df_antigo)
    normaliza_colunas_latlong(df_antigo)
    normaliza_datas_para_brasilia(df_antigo)
    processa_traducao_status(df_antigo)
    adiciona_colaborador_nome(df_antigo, id_to_nome)
    df_antigo.to_excel(ARQUIVO, index=False)
    print(f"Incremental concluído: {atualizados} atualizados, {inseridos} inseridos.")
    print(f"Base final salva em {ARQUIVO} (coluna status_pt e colaborador_nome)")

if __name__ == "__main__":
    gerar_arquivo_atividades()






