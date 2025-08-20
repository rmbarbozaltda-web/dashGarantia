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
            'name': dados.get('name', ''),  # Presumindo que há um campo 'name'
            'order.id': dados.get('order_id', ''),  # Presumindo que há um campo 'order_id'
            'archived': dados.get('archived', False),  # Presumindo que há um campo 'archived'
            'type': item.get('type', 'N/A'),
            'title': item.get('title', ''),  # Adicionando o título da pergunta
            'answer': item.get('answer', ''),
            'score': item.get('score', 0),  # Adicionando score se existir
            'position': item.get('position', -1),  # Adicionando posição
            'createdAt': dados.get('createdAt', '')
        })
    
    return pd.DataFrame(processed_data)  # Retorna um DataFrame

# Função principal para atualizar as respostas
def gerar_arquivo_respostas():
    # Carregar dados de tabela_formularios
    formularios_df = pd.read_excel("tabela_formularios.xlsx")
    
    # Filtrar linhas com "info" válida
    formularios_df = formularios_df[formularios_df["info"] != "NENHUM FORMULÁRIO VINCULADO"]
    
    # Verificar se tabela_respostas existe
    if tabela_respostas_existente():
        respostas_df = pd.read_excel("tabela_respostas.xlsx")
    else:
        respostas_df = pd.DataFrame()  # Iniciar um DataFrame vazio se não existir
    
    # Listas para controle
    ids_formularios = formularios_df["id"].tolist()
    ids_respostas = respostas_df["id"].tolist() if not respostas_df.empty else []

    # Registro de execução
    total_ids = len(ids_formularios)
    print("Iniciando atualização das respostas...")
    start_time = time.time()

    for index, id_form in enumerate(ids_formularios):
        if id_form not in ids_respostas:
            # Buscar na API se id não existe na resposta
            dados = buscar_dados_api(id_form)
            if dados:
                # Processar a resposta da API
                resposta_df = processar_resposta(dados, id_form)
                # Concatenar os dados
                respostas_df = pd.concat([respostas_df, resposta_df], ignore_index=True)

        else:
            # Comparar createdAt se id já existe na tabela_respostas
            createdAt_formulario = formularios_df.loc[formularios_df["id"] == id_form, "createdAt"].values[0]
            createdAt_resposta = respostas_df.loc[respostas_df["id"] == id_form, "createdAt"].values[0]
            
            if createdAt_formulario != createdAt_resposta:
                # Atualizar registro na tabela_respostas
                dados = buscar_dados_api(id_form)
                if dados:
                    resposta_df = processar_resposta(dados, id_form)
                    respostas_df = pd.concat([respostas_df, resposta_df], ignore_index=True)

        # Exibir progresso
        progresso = (index + 1) / total_ids * 100
        elapsed_time = time.time() - start_time
        print(f"Progresso: {progresso:.2f}%, Tempo decorrido: {elapsed_time:.2f} segundos")

    # Salvar tabela_respostas.xlsx
    respostas_df.to_excel("tabela_respostas.xlsx", index=False)
    print("Atualização concluída e salva em tabela_respostas.xlsx")

# Executar a função principal
gerar_arquivo_respostas()












































































