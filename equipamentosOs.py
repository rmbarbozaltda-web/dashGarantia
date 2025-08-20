import pandas as pd
import requests
import os
from tqdm import tqdm
import time

# ========== CONFIGURAÇÕES ==========
EXCEL_OS = 'ordens_de_servico.xlsx'
EXCEL_EQUIP = 'tabela_equipamentos.xlsx'
API_KEY = "ODU1OWZkODItYjU3MC00NjllLTlmYjEtYTA3ZGJjNzBmN2E2OjU3MDE2"
API_URL_EQUIP = "https://carchost.fieldcontrol.com.br/orders/{}/equipments"
HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "X-Api-Key": API_KEY,
}
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # segundos

def normaliza(val):
    return str(val).strip() if pd.notnull(val) and val != "nan" else ""

def busca_equipamentos_with_retries(order_id):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(API_URL_EQUIP.format(order_id), headers=HEADERS, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            print(f"[WARN] Erro de requisição (tentativa {attempt}/{MAX_RETRIES}) para {order_id}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            else:
                return None
        if resp.status_code == 200:
            try:
                dados = resp.json()
            except Exception as e:
                print(f"[WARN] JSON inválido para {order_id} (tentativa {attempt}): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    return None
            items = dados.get('items')
            if isinstance(items, list):
                return items
            else:
                return []
        else:
            print(f"[WARN] Status {resp.status_code} para {order_id} (tentativa {attempt})")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            else:
                return None

def transformar_dict_list_para_str(df):
    for col in df.columns:
        df[col] = df[col].apply(lambda x: str(x) if isinstance(x, (dict, list)) else x)
    return df

def gerar_arquivo_equipamentos():
    print("\n======= INÍCIO DO PROCESSO DE SINCRONIZAÇÃO DE EQUIPAMENTOS =======\n")

    # 1) Carrega tabela de OS
    print("[DEBUG] Lendo ordens_de_servico.xlsx ...")
    df_os = pd.read_excel(EXCEL_OS, dtype=str)
    df_os = df_os[["id", "Numero OS", "Atualizado em (UTC)", "Atualizado em (Brasília)"]].copy()
    df_os["id"] = df_os["id"].apply(normaliza)
    df_os["Numero OS"] = df_os["Numero OS"].apply(normaliza)
    df_os["Atualizado em (UTC)"] = df_os["Atualizado em (UTC)"].apply(normaliza)
    df_os["Atualizado em (Brasília)"] = df_os["Atualizado em (Brasília)"].apply(normaliza)
    print(f"[DEBUG] Total de OS na planilha: {len(df_os)}")

    # 2) Mantém a versão mais recente de cada OS na planilha
    df_os['Atualizado em (UTC)'] = pd.to_datetime(df_os['Atualizado em (UTC)'], errors='coerce')
    df_os.sort_values(by=['id', 'Atualizado em (UTC)'], inplace=True)
    df_os = df_os.groupby('id', as_index=False).last()

    # 3) Carrega base antiga e constrói memória de comparação (mesma lógica válida)
    if os.path.isfile(EXCEL_EQUIP):
        print("[DEBUG] tabela_equipamentos.xlsx existe — comparação incremental")
        df_equip_ant = pd.read_excel(EXCEL_EQUIP, dtype=str)
        colunas_anteriores = list(df_equip_ant.columns)
        if "id_OS" not in df_equip_ant.columns:
            raise KeyError("Arquivo EXCEL_EQUIP deve ter coluna 'id_OS'")
        df_equip_ant["id_OS"] = df_equip_ant["id_OS"].apply(normaliza)
        if "Atualizado em (UTC)" in df_equip_ant.columns:
            df_equip_ant["Atualizado em (UTC)"] = pd.to_datetime(df_equip_ant["Atualizado em (UTC)"], errors='coerce')

        memoria = df_equip_ant.groupby("id_OS", as_index=False).last()
        memoria_ts = memoria[["id_OS", "Atualizado em (UTC)"]].rename(columns={"Atualizado em (UTC)": "Atualizado em (UTC)_ant"})
        memoria_full = df_equip_ant.copy()

        merge = pd.merge(df_os, memoria_ts, left_on="id", right_on="id_OS", how="left", suffixes=("", "_ant"))
        atualizar = merge[
            (merge["Atualizado em (UTC)"] > merge["Atualizado em (UTC)_ant"]) | merge["Atualizado em (UTC)_ant"].isna()
        ]
        os_para_consultar = atualizar[["id", "Numero OS", "Atualizado em (UTC)", "Atualizado em (Brasília)"]].to_dict('records')
        print(f"[DEBUG] Novas OS ou OS alteradas para atualizar: {len(os_para_consultar)}")
        print(f"[DEBUG] Linhas na memória_full (antes): {len(memoria_full)}")
    else:
        print("[DEBUG] tabela_equipamentos.xlsx não existe — irá buscar TODAS as OS")
        os_para_consultar = df_os.to_dict('records')
        memoria_full = pd.DataFrame()
        colunas_anteriores = []
        print(f"[DEBUG] Novas OS ou OS alteradas para atualizar: {len(os_para_consultar)}")
        print(f"[DEBUG] Linhas na memória_full (antes): 0")

    # 4) Consulta equipamentos - GERAR UMA LINHA POR EQUIPAMENTO
    novos_registros = []
    count_api_errors = 0
    for row in tqdm(os_para_consultar, desc="Consultando equipamentos por OS"):
        os_id = row["id"]
        num_os = row["Numero OS"]
        dt_utc = row["Atualizado em (UTC)"]
        dt_br = row.get("Atualizado em (Brasília)", "")
        equips = busca_equipamentos_with_retries(os_id)
        if equips is None:
            count_api_errors += 1
            registro = {
                "id_OS": os_id,
                "Numero OS": num_os,
                "Atualizado em (UTC)": dt_utc,
                "Atualizado em (Brasília)": dt_br,
                "info": "ERRO AO CONSULTAR"
            }
            novos_registros.append(registro)
            continue

        if equips:
            for equip in equips:
                registro = {
                    "id_OS": os_id,
                    "Numero OS": num_os,
                    "Atualizado em (UTC)": dt_utc,
                    "Atualizado em (Brasília)": dt_br
                }
                if isinstance(equip, dict):
                    for k, v in equip.items():
                        # mantém a chave 'id' se for do equipamento — NÃO vamos agrupar por ela depois
                        registro[k] = v
                else:
                    registro["equip_raw"] = str(equip)
                novos_registros.append(registro)
        else:
            registro = {
                "id_OS": os_id,
                "Numero OS": num_os,
                "Atualizado em (UTC)": dt_utc,
                "Atualizado em (Brasília)": dt_br,
                "info": "SEM EQUIPAMENTO VINCULADO"
            }
            novos_registros.append(registro)

    print(f"[DEBUG] Requisições com erro definitivo: {count_api_errors}")
    print(f"[DEBUG] Novos registros (linhas geradas nesta execução): {len(novos_registros)}")

    # 5) Gera nova base: remove registros antigos para as OSs atualizadas e adiciona os novos (uma linha por equipamento)
    if not memoria_full.empty and novos_registros:
        ids_novas = set(r["id"] for r in os_para_consultar)
        memoria_full = memoria_full[~memoria_full["id_OS"].isin(ids_novas)]
        df_novos = pd.DataFrame(novos_registros)

        todas_colunas = list(dict.fromkeys(colunas_anteriores + list(df_novos.columns)))  # mantém ordem preferida
        for c in todas_colunas:
            if c not in memoria_full.columns:
                memoria_full[c] = ""
            if c not in df_novos.columns:
                df_novos[c] = ""
        memoria_full = memoria_full[todas_colunas]
        df_novos = df_novos[todas_colunas]

        memoria_full = transformar_dict_list_para_str(memoria_full)
        df_novos = transformar_dict_list_para_str(df_novos)
        nova_base = pd.concat([memoria_full, df_novos], ignore_index=True, sort=False)
    elif novos_registros:
        df_novos = pd.DataFrame(novos_registros)
        todas_colunas = list(dict.fromkeys(colunas_anteriores + list(df_novos.columns)))
        for c in todas_colunas:
            if c not in df_novos.columns:
                df_novos[c] = ""
        df_novos = df_novos[todas_colunas]
        df_novos = transformar_dict_list_para_str(df_novos)
        nova_base = df_novos.copy()
    else:
        if not memoria_full.empty:
            memoria_full = transformar_dict_list_para_str(memoria_full)
            nova_base = memoria_full.copy()
        else:
            nova_base = pd.DataFrame()

    # 6) Ajustes finais: NÃO agrupar por (id_OS, id) — manter UMA LINHA POR EQUIPAMENTO
    if not nova_base.empty:
        if "Atualizado em (UTC)" in nova_base.columns:
            nova_base["Atualizado em (UTC)"] = pd.to_datetime(nova_base["Atualizado em (UTC)"], errors='coerce')
        # apenas remover duplicatas exatas (linha inteira)
        nova_base = nova_base.drop_duplicates(keep="last")
        # ordenar por id_OS e data
        if "id_OS" in nova_base.columns and "Atualizado em (UTC)" in nova_base.columns:
            nova_base = nova_base.sort_values(by=["id_OS", "Atualizado em (UTC)"])
        elif "id_OS" in nova_base.columns:
            nova_base = nova_base.sort_values(by=["id_OS"])

    # DEBUG: mostrar contagens finais antes de salvar
    print(f"[DEBUG] Linhas memoria_full remanescente: {len(memoria_full) if 'memoria_full' in locals() else 0}")
    print(f"[DEBUG] Linhas totais resultado (nova_base): {len(nova_base)}")

    # 7) Salva
    nova_base.to_excel(EXCEL_EQUIP, index=False)
    print(f"\n[DEBUG] NOVA BASE GERADA: {EXCEL_EQUIP} ({len(nova_base)} registros)")
    print("\n======= FIM DO PROCESSO =======")

if __name__ == "__main__":
    gerar_arquivo_equipamentos()


















