import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime, timedelta
import warnings
import io
import pytz

warnings.filterwarnings('ignore')

# Configuração da página
st.set_page_config(
    page_title="Dashboard Pós-Vendas Topema",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Título principal
st.title("🏭 Dashboard Pós-Vendas Topema")
st.markdown("---")

@st.cache_data
def carregar_dados():
    """Carrega e processa todos os dados necessários"""
    try:
        # Carregando as tabelas
        ordens_servico = pd.read_excel('ordens_de_servico.xlsx')
        atividades = pd.read_excel('atividades.xlsx')
        equipamentos = pd.read_excel('tabela_equipamentos.xlsx')
        respostas = pd.read_excel('tabela_respostas.xlsx')
        depara_etiquetas = pd.read_excel('DePara Etiquetas.xlsx')
        depara_estados = pd.read_excel('DePara Estados.xlsx')

        # --- FILTRAR OS TOTALMENTE ARQUIVADAS ---
        if 'archived' in atividades.columns:
            atividades['archived'] = atividades['archived'].astype(bool)
            status_arquivamento_por_os = atividades.groupby('order')['archived'].all()
            os_ids_para_remover = status_arquivamento_por_os[status_arquivamento_por_os].index.tolist()
            ordens_servico = ordens_servico[~ordens_servico['id'].isin(os_ids_para_remover)]

        # Filtrando apenas ordens de garantia
        ordens_servico = ordens_servico[ordens_servico['Tipo de Serviço'] == 'Garantia']

        # Convertendo datas e tratando timezones
        colunas_data_os = ['Criado em (UTC)', 'Atualizado em (UTC)', 'Atualizado em (Brasília)']
        for col in colunas_data_os:
            if col in ordens_servico.columns:
                ordens_servico[col] = pd.to_datetime(ordens_servico[col], errors='coerce')
                if 'UTC' in col and ordens_servico[col].dt.tz is None:
                    ordens_servico[col] = ordens_servico[col].dt.tz_localize('UTC')

        colunas_data_ativ = ['startedAt', 'completedAt', 'createdAt', 'updatedAt', 'scheduling']
        for col in colunas_data_ativ:
            if col in atividades.columns:
                atividades[col] = pd.to_datetime(atividades[col], errors='coerce')
                if atividades[col].dt.tz is None:
                    atividades[col] = atividades[col].dt.tz_localize('UTC')

        # Aplicando DE/PARA nos estados
        if not depara_estados.empty:
            estado_map = dict(zip(depara_estados['DE'], depara_estados['PARA']))
            ordens_servico['Cliente - Estado'] = ordens_servico['Cliente - Estado'].map(estado_map).fillna(ordens_servico['Cliente - Estado'])

        # Processando etiquetas (equipamentos)
        def processar_etiquetas(row):
            if pd.isna(row['Etiquetas']):
                return []
            etiquetas = [e.strip() for e in str(row['Etiquetas']).split(',')]
            if not depara_etiquetas.empty:
                etiqueta_map = dict(zip(depara_etiquetas['DE'], depara_etiquetas['PARA']))
                etiquetas_processadas = [etiqueta_map.get(e, e) for e in etiquetas]
            else:
                etiquetas_processadas = etiquetas
            return etiquetas_processadas
        ordens_servico['Etiquetas_Processadas'] = ordens_servico.apply(processar_etiquetas, axis=1)

        # LÓGICA DE CONCLUSÃO DAS OS
        def calcular_status_os(os_id):
            atividades_os = atividades[atividades['order'] == os_id].copy()
            if atividades_os.empty:
                return 'Sem Atividade', None, False
            status_abertos = ['Pendente', 'Em andamento', 'Agendada', 'A caminho', 'Em Rota']
            tem_atividade_aberta = atividades_os['status_pt'].isin(status_abertos).any()
            if tem_atividade_aberta:
                ultima_atividade = atividades_os.sort_values('createdAt', ascending=False).iloc[0]
                ultimo_status = ultima_atividade['status_pt']
                data_conclusao = None
                os_concluida = False
            else:
                os_concluida = True
                ultimo_status = 'Concluída'
                atividades_finalizadas = atividades_os[atividades_os['completedAt'].notna()]
                if not atividades_finalizadas.empty:
                    data_conclusao = atividades_finalizadas['completedAt'].max()
                else:
                    data_conclusao = atividades_os['updatedAt'].max()
            return ultimo_status, data_conclusao, os_concluida

        status_info = []
        for os_id in ordens_servico['id']:
            status, data_conclusao, concluida = calcular_status_os(os_id)
            status_info.append({'id': os_id, 'status_final': status, 'data_conclusao': data_conclusao, 'os_concluida': concluida})
        status_df = pd.DataFrame(status_info)
        ordens_servico = ordens_servico.merge(status_df, on='id', how='left')

        # LÓGICA DE CORREÇÃO DE DATAS DE CRIAÇÃO
        mask_data_invalida = (ordens_servico['data_conclusao'].notna()) & (ordens_servico['Criado em (UTC)'].notna()) & (ordens_servico['data_conclusao'] < ordens_servico['Criado em (UTC)'])
        os_ids_para_corrigir = ordens_servico.loc[mask_data_invalida, 'id']
        if not os_ids_para_corrigir.empty:
            atividades_para_correcao = atividades[atividades['order'].isin(os_ids_para_corrigir) & atividades['scheduling'].notna()].copy()
            if not atividades_para_correcao.empty:
                atividades_para_correcao = atividades_para_correcao.sort_values('createdAt')
                ultimas_atividades_agendadas = atividades_para_correcao.drop_duplicates(subset='order', keep='last')
                mapa_datas_corrigidas = ultimas_atividades_agendadas.set_index('order')['scheduling']
                ordens_servico['data_criacao_corrigida'] = ordens_servico['id'].map(mapa_datas_corrigidas)
                ordens_servico['Criado em (UTC)'] = np.where(
                    (mask_data_invalida) & (ordens_servico['data_criacao_corrigida'].notna()),
                    ordens_servico['data_criacao_corrigida'],
                    ordens_servico['Criado em (UTC)']
                )
                ordens_servico = ordens_servico.drop(columns=['data_criacao_corrigida'])

        # AJUSTE DE FUSO HORÁRIO PARA BRASÍLIA
        fuso_horario_br = 'America/Sao_Paulo'
        ordens_servico['Criado em'] = ordens_servico['Criado em (UTC)'].dt.tz_convert(fuso_horario_br)
        ordens_servico['data_conclusao'] = ordens_servico['data_conclusao'].dt.tz_convert(fuso_horario_br)

        return ordens_servico, atividades, equipamentos, respostas, depara_etiquetas, depara_estados
    except Exception as e:
        st.error(f"Erro ao carregar dados: {str(e)}")
        return None, None, None, None, None, None

# Carregando os dados
ordens_servico, atividades, equipamentos, respostas, depara_etiquetas, depara_estados = carregar_dados()

if ordens_servico is not None:
    # Adicionar o logo na barra lateral
    try:
        st.sidebar.image("logo.png", use_container_width=True)
    except Exception as e:
        st.sidebar.warning(f"Não foi possível carregar o logo. Verifique o arquivo de imagem.")

    # Sidebar com filtros
    st.sidebar.header("🔍 Filtros")
    numeros_os = ['Todos'] + sorted(ordens_servico['Numero OS'].dropna().unique().tolist())
    numero_os_selecionado = st.sidebar.selectbox("Número da OS", numeros_os)

    clientes = ['Todos'] + sorted(ordens_servico['Cliente'].dropna().unique().tolist())
    cliente_selecionado = st.sidebar.selectbox("Cliente", clientes)

    estados = ['Todos'] + sorted(ordens_servico['Cliente - Estado'].dropna().unique().tolist())
    estado_selecionado = st.sidebar.selectbox("Estado", estados)

    colaboradores = ['Todos'] + sorted(atividades['colaborador_nome'].dropna().unique().tolist())
    colaborador_selecionado = st.sidebar.selectbox("Colaborador", colaboradores)

    todos_equipamentos = []
    for etiquetas_list in ordens_servico['Etiquetas_Processadas']:
        todos_equipamentos.extend(etiquetas_list)
    equipamentos_unicos = ['Todos'] + sorted(list(set(todos_equipamentos))) if todos_equipamentos else ['Todos']
    equipamento_selecionado = st.sidebar.selectbox("Equipamento", equipamentos_unicos)

    status_os_opcoes = ['Todos', 'Abertos', 'Fechados']
    status_os_selecionado = st.sidebar.selectbox("Status da OS", status_os_opcoes)

    data_min = ordens_servico['Criado em'].min().date()
    data_max = ordens_servico['Criado em'].max().date()
    data_inicio, data_fim = st.sidebar.date_input(
        "Período de Criação",
        value=[data_min, data_max],
        min_value=data_min,
        max_value=data_max,
        format="DD/MM/YYYY"
    )
    st.sidebar.markdown("---")
    sla_dias = st.sidebar.number_input("Meta de SLA (dias)", min_value=1, value=2, step=1)

    # Aplicando filtros
    df_filtrado = ordens_servico.copy()
    if status_os_selecionado == 'Abertos':
        df_filtrado = df_filtrado[df_filtrado['os_concluida'] == False]
    elif status_os_selecionado == 'Fechados':
        df_filtrado = df_filtrado[df_filtrado['os_concluida'] == True]

    if numero_os_selecionado != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['Numero OS'] == numero_os_selecionado]
    if cliente_selecionado != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['Cliente'] == cliente_selecionado]
    if estado_selecionado != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['Cliente - Estado'] == estado_selecionado]
    if equipamento_selecionado != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['Etiquetas_Processadas'].apply(lambda x: equipamento_selecionado in x)]
    
    atividades_filtro_os = atividades[atividades['order'].isin(df_filtrado['id'])]
    if colaborador_selecionado != 'Todos':
        os_ids_colaborador = atividades[atividades['colaborador_nome'] == colaborador_selecionado]['order'].unique()
        df_filtrado = df_filtrado[df_filtrado['id'].isin(os_ids_colaborador)]
        atividades_filtro_os = atividades_filtro_os[atividades_filtro_os['colaborador_nome'] == colaborador_selecionado]

    if data_inicio and data_fim:
        data_inicio_tz = pd.Timestamp(data_inicio, tz='America/Sao_Paulo')
        data_fim_tz = pd.Timestamp(data_fim, tz='America/Sao_Paulo') + pd.Timedelta(days=1)
        df_filtrado = df_filtrado[(df_filtrado['Criado em'] >= data_inicio_tz) & (df_filtrado['Criado em'] < data_fim_tz)]

    # --- SEÇÃO DE CARDS DE KPI ---
    st.header("📊 Indicadores Chave")

    # CSS para os cards customizados
    card_style = """
    <style>
    .card {
        background-color: #1e293b; /* Fundo escuro */
        color: #e2e8f0; /* Texto claro */
        width: 100%;
        height: 140px;
        padding: 20px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        border-radius: 12px;
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.1);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }
    .card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.2);
    }
    .card-total { border-left: 6px solid #0ea5e9; } /* Azul vibrante */
    .card-concluidas { border-left: 6px solid #22c55e; } /* Verde vibrante */
    .card-abertas { border-left: 6px solid #f59e0b; } /* Amarelo/Âmbar vibrante */
    .card-sla { border-left: 6px solid #ef4444; } /* Vermelho vibrante */
    .card h2 {
        margin: 0 0 10px 0;
        font-size: 1.2em;
        font-weight: 600;
        text-align: center;
        color: #94a3b8; /* Cor do título mais suave */
    }
    .card .numero {
        margin: 0;
        font-size: 2.5em;
        font-weight: bold;
        color: #f8fafc; /* Cor do número bem clara */
    }
    </style>
    """
    st.markdown(card_style, unsafe_allow_html=True)

    # Cálculos dos KPIs
    total_os = len(df_filtrado)
    os_concluidas_count = df_filtrado['os_concluida'].sum()
    os_abertas_count = total_os - os_concluidas_count
    
    df_concluidas_sla = df_filtrado[df_filtrado['os_concluida']].copy()
    if not df_concluidas_sla.empty:
        df_concluidas_sla['sla'] = (df_concluidas_sla['data_conclusao'] - df_concluidas_sla['Criado em']).dt.days
        sla_medio = df_concluidas_sla['sla'].mean()
        sla_medio_str = f"{sla_medio:.1f} dias" if pd.notna(sla_medio) else "N/A"
    else:
        sla_medio = 0
        sla_medio_str = "N/A"

    # Exibição dos KPIs com os cards customizados
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="card card-total"><h2>Total de OS</h2><p class="numero">{total_os}</p></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="card card-concluidas"><h2>OS Concluídas</h2><p class="numero">{os_concluidas_count}</p></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="card card-abertas"><h2>OS em Aberto</h2><p class="numero">{os_abertas_count}</p></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="card card-sla"><h2>SLA Médio</h2><p class="numero">{sla_medio_str}</p></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # --- SEÇÃO DE GRÁFICOS PRINCIPAIS ---
    col1, col2 = st.columns([1, 2])
    with col1:
        # <<< INÍCIO DA SEÇÃO DO GRÁFICO VELOCÍMETRO CORRIGIDO >>>
        st.subheader("Atingimento da Meta de SLA")

        # --- Lógica para calcular o percentual de atingimento do SLA ---
        percentual_sla = 0 # Valor padrão
        if not df_concluidas_sla.empty:
            # A coluna 'sla' já foi calculada em dias anteriormente
            os_dentro_prazo = (df_concluidas_sla['sla'] <= sla_dias).sum()
            total_concluidas = len(df_concluidas_sla)
            
            # Calcula o percentual, evitando divisão por zero
            if total_concluidas > 0:
                percentual_sla = (os_dentro_prazo / total_concluidas) * 100

        # --- Criação do gráfico de velocímetro com o percentual ---
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=percentual_sla,
            number={'suffix': '%', 'font': {'size': 40}},
            title={'text': f"Meta: {sla_dias} dias", 'font': {'size': 20}},
            gauge={
                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
                'bar': {'color': "#0ea5e9"},
                'bgcolor': "white",
                'borderwidth': 2,
                'bordercolor': "gray",
                'steps': [
                    {'range': [0, 50], 'color': '#ef4444'},   # Vermelho
                    {'range': [50, 80], 'color': '#f59e0b'},  # Amarelo
                    {'range': [80, 100], 'color': '#22c55e'}  # Verde
                ],
            },
            domain={'x': [0, 1], 'y': [0, 1]}
        ))
        
        fig_gauge.update_layout(
            height=500, # Altura ajustada para alinhar com o gráfico de barras
            margin=dict(l=20, r=20, t=50, b=20)
        )
        # <<< FIM DA SEÇÃO DO GRÁFICO VELOCÍMETRO >>>
        
        st.plotly_chart(fig_gauge, use_container_width=True)

    with col2:
        st.subheader("OS Criadas vs Concluídas")
        df_filtrado['mes_ano_criacao'] = df_filtrado['Criado em'].dt.to_period('M').astype(str)
        df_filtrado['mes_ano_conclusao'] = df_filtrado['data_conclusao'].dt.to_period('M').astype(str)
        
        criadas_por_mes = df_filtrado.groupby('mes_ano_criacao').size().reset_index(name='criadas')
        criadas_por_mes.rename(columns={'mes_ano_criacao': 'mes_ano'}, inplace=True)
        
        concluidas_por_mes = df_filtrado[df_filtrado['os_concluida']].groupby('mes_ano_conclusao').size().reset_index(name='concluidas')
        concluidas_por_mes.rename(columns={'mes_ano_conclusao': 'mes_ano'}, inplace=True)
        
        tendencia_df = pd.merge(criadas_por_mes, concluidas_por_mes, on='mes_ano', how='outer').fillna(0)
        tendencia_df = tendencia_df.sort_values('mes_ano')
        
        fig_tendencia = go.Figure()
        fig_tendencia.add_trace(go.Bar(
            x=tendencia_df['mes_ano'], 
            y=tendencia_df['criadas'], 
            name='Criadas', 
            marker_color='#0ea5e9', # Azul vibrante
            text=tendencia_df['criadas'],
            textposition='auto'
        ))
        fig_tendencia.add_trace(go.Bar(
            x=tendencia_df['mes_ano'], 
            y=tendencia_df['concluidas'], 
            name='Concluídas', 
            marker_color='#22c55e', # Verde vibrante
            text=tendencia_df['concluidas'],
            textposition='auto'
        ))
        
        max_y = 0
        if not tendencia_df.empty:
            max_y = max(tendencia_df['criadas'].max(), tendencia_df['concluidas'].max()) * 1.15
        
        fig_tendencia.update_layout(
            barmode='group', 
            height=500, # Altura aumentada
            xaxis_title="Mês/Ano", 
            yaxis_title="Quantidade de OS", 
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis=dict(range=[0, max_y])
        )
        st.plotly_chart(fig_tendencia, use_container_width=True)

    # --- SEÇÃO DE GRÁFICOS DE BARRAS ---
    st.markdown("---")
    st.header("📋 Análises por Categoria")

    if not df_filtrado.empty:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Top 10 Colaboradores - Atividades")
            colaborador_counts = atividades_filtro_os['colaborador_nome'].value_counts().head(10)
            fig_colab = px.bar(x=colaborador_counts.index, y=colaborador_counts.values, text=colaborador_counts.values)
            fig_colab.update_traces(textposition='outside', texttemplate='%{text}', marker_color='#1f77b4')
            fig_colab.update_layout(height=400, xaxis_title="Colaboradores", yaxis_title="Número de Atividades", xaxis_tickangle=-45, yaxis=dict(range=[0, colaborador_counts.max() * 1.15 if not colaborador_counts.empty else 10]))
            st.plotly_chart(fig_colab, use_container_width=True)

        with col2:
            st.subheader("Top 10 Estados - Quantidade de OS")
            estado_counts = df_filtrado['Cliente - Estado'].value_counts().head(10)
            fig_estados = px.bar(x=estado_counts.index, y=estado_counts.values, text=estado_counts.values)
            fig_estados.update_traces(textposition='outside', texttemplate='%{text}', marker_color='#1f77b4')
            fig_estados.update_layout(height=400, xaxis_title="Estados", yaxis_title="Quantidade de OS", xaxis_tickangle=-45, yaxis=dict(range=[0, estado_counts.max() * 1.15 if not estado_counts.empty else 10]))
            st.plotly_chart(fig_estados, use_container_width=True)
        
        # Gráfico de Equipamentos
        st.subheader("Top 10 Equipamentos com mais OS")
        df_equipamentos = df_filtrado.explode('Etiquetas_Processadas')
        equipamentos_counts = df_equipamentos['Etiquetas_Processadas'].value_counts().head(10)
        if not equipamentos_counts.empty:
            fig_equip = px.bar(x=equipamentos_counts.index, y=equipamentos_counts.values, text=equipamentos_counts.values)
            fig_equip.update_traces(textposition='outside', texttemplate='%{text}', marker_color='#ff7f0e')
            fig_equip.update_layout(height=400, xaxis_title="Equipamentos", yaxis_title="Quantidade de OS", xaxis_tickangle=-45, yaxis=dict(range=[0, equipamentos_counts.max() * 1.15]))
            st.plotly_chart(fig_equip, use_container_width=True)
        else:
            st.info("Nenhum equipamento encontrado para os filtros selecionados.")

    # Análise de Falhas, Causas e Ações
    st.markdown("---")
    st.header("🔧 Análise de Falhas, Causas e Ações")
    if 'name' in respostas.columns and 'title' in respostas.columns and 'answer' in respostas.columns:
        respostas_base_falhas = respostas[respostas['name'].astype(str).str.contains('FALHA', case=False, na=False)].copy()
        link_column_name = None
        if 'id_OS' in respostas_base_falhas.columns: link_column_name = 'id_OS'
        elif 'order' in respostas_base_falhas.columns: link_column_name = 'order'
        elif 'order.id' in respostas_base_falhas.columns: link_column_name = 'order.id'

        if link_column_name:
            respostas_filtradas = respostas_base_falhas[respostas_base_falhas[link_column_name].isin(df_filtrado['id'])]
            if not respostas_filtradas.empty:
                df_falhas = respostas_filtradas[respostas_filtradas['title'] == "QUAL A FALHA DO EQUIPAMENTO?"].copy()
                df_causas = respostas_filtradas[respostas_filtradas['title'].astype(str).str.contains("QUAL A CAUSA DA FALHA", case=False, na=False)].copy()
                perguntas_acao = ["QUAL A AÇÃO TOMADA PARA RESOLVER O PROBLEMA?", "QUAL AÇÃO FOI TOMADA?", "QUAL A AÇÃO TOMADA?"]
                df_acoes = respostas_filtradas[respostas_filtradas['title'].isin(perguntas_acao)].copy()
                if not df_acoes.empty:
                    df_acoes['answer'] = df_acoes['answer'].str.split(',')
                    df_acoes = df_acoes.explode('answer')
                    df_acoes['answer'] = df_acoes['answer'].str.strip()

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.subheader("Top 10 Falhas")
                    if not df_falhas.empty:
                        falhas_counts = df_falhas['answer'].value_counts().head(10)
                        fig = px.bar(y=falhas_counts.index, x=falhas_counts.values, orientation='h', text=falhas_counts.values)
                        fig.update_layout(yaxis={'categoryorder':'total ascending'}, height=500, xaxis_title="Quantidade", yaxis_title="")
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Nenhuma falha identificada.")
                with col2:
                    st.subheader("Top 10 Causas")
                    if not df_causas.empty:
                        causas_counts = df_causas['answer'].value_counts().head(10)
                        fig = px.bar(y=causas_counts.index, x=causas_counts.values, orientation='h', text=causas_counts.values)
                        fig.update_layout(yaxis={'categoryorder':'total ascending'}, height=500, xaxis_title="Quantidade", yaxis_title="")
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Nenhuma causa identificada.")
                with col3:
                    st.subheader("Top 10 Ações Corretivas")
                    if not df_acoes.empty:
                        acoes_counts = df_acoes['answer'].value_counts().head(10)
                        fig = px.bar(y=acoes_counts.index, x=acoes_counts.values, orientation='h', text=acoes_counts.values)
                        fig.update_layout(yaxis={'categoryorder':'total ascending'}, height=500, xaxis_title="Quantidade", yaxis_title="")
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Nenhuma ação identificada.")
            else:
                st.info("Nenhum formulário de falha encontrado para as OS filtradas.")
        else:
            st.warning("Não foi possível encontrar uma coluna de vínculo ('id_OS', 'order' ou 'order.id') na tabela de respostas.")
    else:
        st.warning("As colunas 'name', 'title' e/ou 'answer' não foram encontradas na tabela de respostas.")

    # --- SEÇÃO AGENDA DOS TÉCNICOS ---
    st.markdown("---")
    st.header("🗓️ Agenda dos Técnicos")
    data_agenda = st.date_input(
        "Selecione uma data para ver a agenda",
        datetime.now(),
        format="DD/MM/YYYY"
    )
    os_garantia_ids = ordens_servico['id'].unique()
    atividades_agendadas = atividades[
        (atividades['order'].isin(os_garantia_ids)) &
        (atividades['archived'] == False) &
        (atividades['scheduling'].notna())
    ].copy()

    if not atividades_agendadas.empty and data_agenda:
        fuso_horario_br = 'America/Sao_Paulo'
        data_selecionada_tz = pd.Timestamp(data_agenda, tz=fuso_horario_br)
        atividades_do_dia = atividades_agendadas[atividades_agendadas['scheduling'].dt.date == data_selecionada_tz.date()]

        if not atividades_do_dia.empty:
            agenda_df = pd.merge(
                atividades_do_dia,
                df_filtrado[['id', 'Numero OS', 'Cliente']],
                left_on='order',
                right_on='id',
                how='left'
            )
            agenda_df.dropna(subset=['Numero OS'], inplace=True)
            
            def criar_url_mapa(coords):
                if pd.notna(coords) and isinstance(coords, str) and ',' in coords:
                    coords_limpas = coords.replace(" ", "")
                    return f"https://www.google.com/maps/search/?api=1&query={coords_limpas}"
                return None
            
            agenda_df['map_url'] = agenda_df['coords'].apply(criar_url_mapa)
            
            agenda_display = agenda_df[['scheduling', 'colaborador_nome', 'map_url', 'Numero OS', 'Cliente']].copy()
            agenda_display.columns = ['Horário', 'Técnico', 'Localização', 'Número OS', 'Cliente']
            agenda_display = agenda_display.sort_values(by='Horário')
            
            st.dataframe(
                agenda_display,
                column_config={
                    "Horário": st.column_config.TimeColumn(
                        "Horário",
                        format="HH:mm",
                    ),
                    "Localização": st.column_config.LinkColumn(
                        "Localização",
                        help="Clique para abrir o local no Google Maps",
                        display_text="🗺️"
                    )
                },
                hide_index=True,
                use_container_width=False
            )
        else:
            st.info(f"Nenhuma atividade agendada para o dia {data_agenda.strftime('%d/%m/%Y')}.")
    else:
        st.info("Nenhuma atividade agendada encontrada.")

    st.markdown("---")
    # Tabela resumo
    st.header("📋 Tabela Resumo das OS")
    if not df_filtrado.empty:
        df_display = df_filtrado[[
            'Numero OS', 'Cliente', 'Cliente - Estado', 'Criado em',
            'status_final', 'data_conclusao', 'os_concluida', 'link'
        ]].copy()
        df_display['os_concluida'] = df_display['os_concluida'].map({True: '✅ Sim', False: '❌ Não'})
        df_display.columns = ['Número OS', 'Cliente', 'Estado', 'Criado em', 'Status Final', 'Data Conclusão', 'Concluída', 'link']
        
        st.dataframe(
            df_display,
            use_container_width=True,
            column_config={
                "link": st.column_config.LinkColumn(
                    "Relatório",
                    help="Clique para abrir o relatório.",
                    display_text="📄"
                ),
                "Criado em": st.column_config.DatetimeColumn(
                    "Criado em",
                    format="DD/MM/YYYY HH:mm",
                ),
                "Data Conclusão": st.column_config.DatetimeColumn(
                    "Data Conclusão",
                    format="DD/MM/YYYY HH:mm",
                )
            },
            hide_index=True
        )

        @st.cache_data
        def to_excel(df):
            df_export = df.copy()
            df_export['Criado em'] = df_export['Criado em'].apply(lambda x: x.strftime('%d/%m/%Y %H:%M') if pd.notna(x) else 'N/A')
            df_export['Data Conclusão'] = df_export['Data Conclusão'].apply(lambda x: x.strftime('%d/%m/%Y %H:%M') if pd.notna(x) else 'N/A')
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='OS_Filtradas')
            processed_data = output.getvalue()
            return processed_data

        excel_data = to_excel(df_display)
        st.download_button(
            label="📥 Baixar Dados Filtrados (XLSX)",
            data=excel_data,
            file_name=f"os_filtradas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Nenhuma OS encontrada com os filtros aplicados.")
else:
    st.error("Não foi possível carregar os dados. Verifique se todos os arquivos estão na pasta correta.")
    st.info("Arquivos necessários: ordens_de_servico.xlsx, atividades.xlsx, tabela_equipamentos.xlsx, tabela_respostas.xlsx, DePara Etiquetas.xlsx, DePara Estados.xlsx")
