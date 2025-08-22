import pandas as pd
import requests
import os
import time

# Configurações
API_URL = "https://carchost.fieldcontrol.com.br/forms-answers/"
API_KEY = "ODU1OWZkODItYjU3MC00NjllLTlmYjEtYTA3ZGJjNzBmN2E2OjU3MDE2"
HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "X-Api-Key": API_KEY,
}

# Função para verificar a existência da tabela_respostas
def tabela_respostas_existente():
    return os.path.exists("tabela_respostas.xlsx")

# Função para buscar dados da API
def buscar_dados_api(id_form):
    response = requests.get(API_URL + str(id_form), headers=HEADERS)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erro ao buscar dados para o id {id_form}: {response.status_code}")
        return None

# Função para processar a resposta da API
def processar_resposta(dados, id_form):
    processed_data = []
    for item in dados.get('questions', []):
        # Extrair informações necessárias
        processed_data.append({
            'id': id_form,
            'name': dados.get('name', ''),
            'archived': dados.get('archived', False),
            'type': item.get('type', 'N/A'),
            'title': item.get('title', ''),
            'answer': item.get('answer', ''),
            'score': item.get('score', 0),
            'position': item.get('position', -1),
            'createdAt': dados.get('createdAt', '')
        })
    return pd.DataFrame(processed_data)

# Função principal para atualizar as respostas
def gerar_arquivo_respostas():
    # Carregar dados de tabela_formularios
    formularios_df = pd.read_excel("tabela_formularios.xlsx")
    # Filtrar linhas com "info" válida
    formularios_df_validos = formularios_df[formularios_df["info"] != "NENHUM FORMULÁRIO VINCULADO"].copy()
    
    # Verificar se tabela_respostas existe
    if tabela_respostas_existente():
        respostas_df = pd.read_excel("tabela_respostas.xlsx")
    else:
        respostas_df = pd.DataFrame()
        
    # Listas para controle
    ids_formularios = formularios_df_validos["id"].tolist()
    ids_respostas = respostas_df["id"].tolist() if not respostas_df.empty else []
    
    # Registro de execução
    total_ids = len(ids_formularios)
    print("Iniciando atualização das respostas...")
    start_time = time.time()
    
    novas_respostas = [] # Lista para armazenar os novos dataframes
    
    for index, id_form in enumerate(ids_formularios):
        precisa_buscar = False
        if id_form not in ids_respostas:
            precisa_buscar = True
        else:
            # Comparar createdAt se id já existe na tabela_respostas
            createdAt_formulario = formularios_df_validos.loc[formularios_df_validos["id"] == id_form, "createdAt"].values[0]
            createdAt_resposta = respostas_df.loc[respostas_df["id"] == id_form, "createdAt"].values[0]
            if createdAt_formulario != createdAt_resposta:
                # Marcar para remover o antigo e buscar o novo
                respostas_df = respostas_df[respostas_df['id'] != id_form]
                precisa_buscar = True
                
        if precisa_buscar:
            dados = buscar_dados_api(id_form)
            if dados:
                resposta_df = processar_resposta(dados, id_form)
                novas_respostas.append(resposta_df)
                
        # Exibir progresso
        progresso = (index + 1) / total_ids * 100
        elapsed_time = time.time() - start_time
        print(f"Progresso: {progresso:.2f}%, Tempo decorrido: {elapsed_time:.2f} segundos", end='\r')
        
    print("\nProcessamento da API concluído. Consolidando dados...")
    
    # Concatenar todas as novas respostas de uma vez (mais eficiente)
    if novas_respostas:
        respostas_df = pd.concat([respostas_df] + novas_respostas, ignore_index=True)
        
    # Criar um "mapa" com as colunas que queremos adicionar
    mapa_os = formularios_df[['id', 'id_OS', 'Numero OS']]
    
    # CORREÇÃO: Remover as colunas do mapa que já possam existir em respostas_df antes do merge
    colunas_para_remover = [col for col in ['id_OS', 'Numero OS'] if col in respostas_df.columns]
    if colunas_para_remover:
        respostas_df = respostas_df.drop(columns=colunas_para_remover)

    # Fazer o merge para adicionar 'id_OS' e 'Numero OS' à tabela de respostas
    respostas_df_final = pd.merge(respostas_df, mapa_os, on='id', how='left')
    
    # <<< NOVA ALTERAÇÃO: Remover as linhas onde 'archived' é True >>>
    respostas_df_final = respostas_df_final[respostas_df_final['archived'] == False]
    
    # Salvar o dataframe final, já com as colunas da OS
    respostas_df_final.to_excel("tabela_respostas.xlsx", index=False)
    
    print("Atualização concluída e salva em tabela_respostas.xlsx")

# Executar a função principal
gerar_arquivo_respostas()














































































