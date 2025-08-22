import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime, timedelta
import warnings
import io

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

    # Filtros
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
        df_filtrado = df_filtrado[df_filtrado['Etiquetas_Processadas'].apply(
            lambda x: equipamento_selecionado in x
        )]
    if colaborador_selecionado != 'Todos':
        atividades_filtradas = atividades[atividades['colaborador_nome'] == colaborador_selecionado]
        os_ids_colaborador = atividades_filtradas['order'].unique()
        df_filtrado = df_filtrado[df_filtrado['id'].isin(os_ids_colaborador)]

    df_filtrado = df_filtrado[
        (df_filtrado['Criado em'].dt.date >= data_inicio) &
        (df_filtrado['Criado em'].dt.date <= data_fim)
    ]

    # Métricas
    total_os = len(df_filtrado)
    os_concluidas = df_filtrado['os_concluida'].sum()
    os_abertas = total_os - os_concluidas
    tempo_medio_resolucao = np.nan
    percentual_sla = 0

    os_concluidas_df = df_filtrado[df_filtrado['os_concluida']].copy()
    if not os_concluidas_df.empty:
        os_concluidas_df['tempo_resolucao'] = (os_concluidas_df['data_conclusao'] - os_concluidas_df['Criado em']).dt.days
        tempo_medio_resolucao = os_concluidas_df['tempo_resolucao'].mean()
        os_concluidas_df['dentro_sla'] = os_concluidas_df['tempo_resolucao'] <= sla_dias
        percentual_sla = (os_concluidas_df['dentro_sla'].sum() / len(os_concluidas_df)) * 100 if len(os_concluidas_df) > 0 else 0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total de OS", f"{total_os}")
    col2.metric("OS Concluídas", f"{os_concluidas}")
    col3.metric("OS em Aberto", f"{os_abertas}")
    col4.metric("SLA de Atendimento", f"{percentual_sla:.2f}%")
    col5.metric("Tempo Médio (dias)", f"{tempo_medio_resolucao:.1f}" if not np.isnan(tempo_medio_resolucao) else "N/A")
    st.markdown("---")

    # --- SEÇÃO DE GRÁFICOS (AJUSTADO) ---
    st.header("📊 Análises Visuais")
    if not df_filtrado.empty:
        col1, col2 = st.columns(2)

        with col1:
            # Gráfico 1: Distribuição de Status (BARRAS)
            st.subheader("Distribuição de Status das OS")
            status_counts = df_filtrado['os_concluida'].value_counts()
            status_labels_map = {True: 'Concluídas', False: 'Em Aberto'}
            status_counts.index = status_counts.index.map(status_labels_map)

            fig_status = px.bar(
                status_counts,
                x=status_counts.index,
                y=status_counts.values,
                text=status_counts.values,
                color=status_counts.index,
                color_discrete_map={'Concluídas': '#2ca02c', 'Em Aberto': '#d62728'},
                labels={'x': 'Status', 'y': 'Quantidade de OS'}
            )
            fig_status.update_traces(textposition='outside')
            fig_status.update_layout(
                showlegend=False,
                yaxis=dict(range=[0, status_counts.max() * 1.15 if not status_counts.empty else 10])
            )
            st.plotly_chart(fig_status, use_container_width=True)

        with col2:
            # Gráfico 2: Análise de SLA (PIZZA)
            st.subheader("Análise de SLA (OS Concluídas)")
            if not os_concluidas_df.empty:
                sla_counts = os_concluidas_df['dentro_sla'].value_counts()
                sla_labels_map = {True: 'Dentro do SLA', False: 'Fora do SLA'}
                sla_counts.index = sla_counts.index.map(sla_labels_map)

                fig_sla = px.pie(
                    values=sla_counts.values,
                    names=sla_counts.index,
                    color=sla_counts.index,
                    color_discrete_map={'Dentro do SLA': '#2ca02c', 'Fora do SLA': '#d62728'},
                    hole=.3
                )
                fig_sla.update_traces(textinfo='percent+value', textposition='auto', pull=[0.05, 0])
                st.plotly_chart(fig_sla, use_container_width=True)
            else:
                st.info("Nenhuma OS concluída para análise de SLA.")
    else:
        st.info("Nenhuma OS encontrada para exibir análises.")
    st.markdown("---")

    # Gráficos de Barras
    st.header("📈 Análises Detalhadas")

    st.subheader("Backlog de OS em Aberto por Idade")
    os_abertas_df = df_filtrado[~df_filtrado['os_concluida']].copy()
    if not os_abertas_df.empty:
        os_abertas_df['idade_os'] = (datetime.now(os_abertas_df['Criado em'].dt.tz) - os_abertas_df['Criado em']).dt.days
        bins = [-1, 7, 15, 30, np.inf]
        labels = ['Até 7 dias', '8 a 15 dias', '16 a 30 dias', 'Mais de 30 dias']
        os_abertas_df['faixa_idade'] = pd.cut(os_abertas_df['idade_os'], bins=bins, labels=labels)
        backlog_counts = os_abertas_df['faixa_idade'].value_counts().reindex(labels)
        fig_backlog = px.bar(x=backlog_counts.index, y=backlog_counts.values, text=backlog_counts.values, color=backlog_counts.index, color_discrete_map={'Até 7 dias': '#2ca02c', '8 a 15 dias': '#ff7f0e', '16 a 30 dias': '#d62728', 'Mais de 30 dias': '#8c564b'})
        fig_backlog.update_traces(textposition='outside')
        fig_backlog.update_layout(height=400, xaxis_title="Idade da OS", yaxis_title="Quantidade de OS", showlegend=False, yaxis=dict(range=[0, backlog_counts.max() * 1.15 if not backlog_counts.empty else 10]))
        st.plotly_chart(fig_backlog, use_container_width=True)
    else:
        st.info("Nenhuma OS em aberto no período.")

    st.markdown("---")
    st.subheader("Abertura vs. Fechamento de OS por Mês")
    if not df_filtrado.empty:
        # Preparar dados de abertura
        df_filtrado['MesAno_Abertura'] = df_filtrado['Criado em'].dt.to_period('M')
        os_abertas_mes = df_filtrado.groupby('MesAno_Abertura').size()
        os_abertas_mes.name = 'Abertas'

        # Preparar dados de fechamento
        df_fechadas = df_filtrado[df_filtrado['os_concluida']].copy()
        df_fechadas['MesAno_Fechamento'] = df_fechadas['data_conclusao'].dt.to_period('M')
        os_fechadas_mes = df_fechadas.groupby('MesAno_Fechamento').size()
        os_fechadas_mes.name = 'Fechadas'

        # Combinar os dados
        df_mes = pd.concat([os_abertas_mes, os_fechadas_mes], axis=1).fillna(0).astype(int)
        df_mes.index = df_mes.index.strftime('%Y-%m') # Formatar o índice para exibição

        # Criar o gráfico
        fig_abertura_fechamento = go.Figure()
        fig_abertura_fechamento.add_trace(go.Bar(
            x=df_mes.index,
            y=df_mes['Abertas'],
            name='OS Abertas',
            marker_color='#1f77b4',
            text=df_mes['Abertas']
        ))
        fig_abertura_fechamento.add_trace(go.Bar(
            x=df_mes.index,
            y=df_mes['Fechadas'],
            name='OS Fechadas',
            marker_color='#2ca02c',
            text=df_mes['Fechadas']
        ))

        fig_abertura_fechamento.update_traces(textposition='outside')
        fig_abertura_fechamento.update_layout(
            barmode='group',
            height=400,
            xaxis_title="Mês",
            yaxis_title="Quantidade de OS",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig_abertura_fechamento, use_container_width=True)
    else:
        st.info("Nenhum dado para exibir o gráfico de Abertura vs. Fechamento.")

    if not df_filtrado.empty:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Top 10 Colaboradores - Atividades")
            atividades_filtro_os = atividades[atividades['order'].isin(df_filtrado['id'])]
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

    # Análise de Falhas, Causas e Ações
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
            agenda_display = agenda_df[['scheduling', 'colaborador_nome', 'Numero OS', 'Cliente']].copy()
            agenda_display.columns = ['Horário', 'Técnico', 'Número OS', 'Cliente']
            agenda_display = agenda_display.sort_values(by='Horário')

            st.dataframe(
                agenda_display,
                column_config={
                    "Horário": st.column_config.TimeColumn(
                        "Horário",
                        format="HH:mm",
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
