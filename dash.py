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

            atividades_com_conclusao = atividades_os[atividades_os['completedAt'].notna()]
            atividades_sem_conclusao = atividades_os[atividades_os['completedAt'].isna()]
            todas_finalizadas = len(atividades_sem_conclusao) == 0 and len(atividades_com_conclusao) > 0

            if todas_finalizadas:
                data_conclusao = atividades_com_conclusao['completedAt'].max()
                ultimo_status = 'Concluída'
            else:
                ultima_atividade = atividades_os.loc[atividades_os['createdAt'].idxmax()]
                ultimo_status = ultima_atividade['status_pt']
                data_conclusao = None
                todas_finalizadas = False
            return ultimo_status, data_conclusao, todas_finalizadas

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

        # Filtrando apenas respostas de formulários com "FALHA"
        respostas_falhas = respostas[respostas['name'].str.contains('FALHA', case=False, na=False)]

        return ordens_servico, atividades, equipamentos, respostas_falhas, depara_etiquetas, depara_estados

    except Exception as e:
        st.error(f"Erro ao carregar dados: {str(e)}")
        return None, None, None, None, None, None

# Carregando os dados
ordens_servico, atividades, equipamentos, respostas_falhas, depara_etiquetas, depara_estados = carregar_dados()

if ordens_servico is not None:
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

    data_min = ordens_servico['Criado em'].min().date()
    data_max = ordens_servico['Criado em'].max().date()

    # AJUSTE 3: Adicionado o formato de data
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
    if data_inicio and data_fim:
        fuso_horario_br = 'America/Sao_Paulo'
        start_date = pd.to_datetime(data_inicio).tz_localize(fuso_horario_br)
        end_date = pd.to_datetime(data_fim).tz_localize(fuso_horario_br) + timedelta(days=1)
        df_filtrado = df_filtrado[
            (df_filtrado['Criado em'] >= start_date) &
            (df_filtrado['Criado em'] < end_date)
        ]

    # Métricas principais
    st.header("📊 Métricas Gerais")
    total_os = len(df_filtrado)
    os_concluidas_df = df_filtrado[df_filtrado['os_concluida'] == True]
    os_concluidas = len(os_concluidas_df)
    os_em_aberto = total_os - os_concluidas
    taxa_conclusao = (os_concluidas / total_os * 100) if total_os > 0 else 0

    if not os_concluidas_df.empty:
        os_concluidas_df['tempo_resolucao'] = (os_concluidas_df['data_conclusao'] - os_concluidas_df['Criado em']).dt.days
        os_dentro_sla = os_concluidas_df[os_concluidas_df['tempo_resolucao'] <= sla_dias]
        percentual_dentro_sla = (len(os_dentro_sla) / len(os_concluidas_df) * 100) if len(os_concluidas_df) > 0 else 0
    else:
        percentual_dentro_sla = 0

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1: st.metric("Total de OS", total_os)
    with col2: st.metric("OS Concluídas", os_concluidas, f"{taxa_conclusao:.1f}%")
    with col3: st.metric("OS em Aberto", os_em_aberto)
    with col4:
        if not os_concluidas_df.empty:
            tempo_medio_dias = os_concluidas_df['tempo_resolucao'].mean()
            st.metric("Tempo Médio Resolução", f"{tempo_medio_dias:.1f} dias")
        else:
            st.metric("Tempo Médio Resolução", "N/A")
    with col5: st.metric("% OS Dentro do SLA", f"{percentual_dentro_sla:.1f}%", help=f"Meta de SLA: {sla_dias} dias")
    st.markdown("---")

    # Análise de SLA e Backlog
    st.header("⏱️ Análise de SLA e Backlog")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Desempenho de SLA (OS Concluídas)")
        if not os_concluidas_df.empty:
            sla_counts = os_concluidas_df['tempo_resolucao'].apply(lambda x: 'Dentro do SLA' if x <= sla_dias else 'Fora do SLA').value_counts()
            fig_sla = px.pie(values=sla_counts.values, names=sla_counts.index, hole=0.4, color_discrete_sequence=['#2ca02c', '#d62728'])
            fig_sla.update_traces(textposition='inside', textinfo='percent+label')
            fig_sla.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig_sla, use_container_width=True)
        else:
            st.info("Nenhuma OS concluída no período para análise de SLA.")
    with col2:
        st.subheader("Análise de Backlog (OS em Aberto)")
        os_abertas_df = df_filtrado[df_filtrado['os_concluida'] == False].copy()
        if not os_abertas_df.empty:
            agora_br = pd.Timestamp.now(tz='America/Sao_Paulo')
            os_abertas_df['idade_os'] = (agora_br - os_abertas_df['Criado em']).dt.days
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

    # Análises visuais
    st.header("📈 Análises Visuais")
    if not df_filtrado.empty:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Distribuição de Status das OS")
            status_counts = df_filtrado['os_concluida'].value_counts()
            status_labels = ['Concluídas' if x else 'Em Aberto' for x in status_counts.index]
            fig_pizza = px.pie(values=status_counts.values, names=status_labels, color_discrete_sequence=['#2ca02c', '#d62728'])
            fig_pizza.update_traces(textposition='inside', textinfo='percent+label')
            fig_pizza.update_layout(height=400)
            st.plotly_chart(fig_pizza, use_container_width=True)

        with col2:
            st.subheader("Evolução Mensal - OS Criadas vs Concluídas")
            df_filtrado['mes_criacao'] = df_filtrado['Criado em'].dt.to_period('M').astype(str)
            os_criadas_mes = df_filtrado.groupby('mes_criacao').size().reset_index(name='OS Criadas')

            df_concluidas = df_filtrado[df_filtrado['data_conclusao'].notna()].copy()
            df_concluidas['mes_conclusao'] = df_concluidas['data_conclusao'].dt.to_period('M').astype(str)
            os_concluidas_mes = df_concluidas.groupby('mes_conclusao').size().reset_index(name='OS Concluídas')

            evolucao_mensal = pd.merge(os_criadas_mes, os_concluidas_mes, left_on='mes_criacao', right_on='mes_conclusao', how='outer')
            evolucao_mensal['Mês'] = evolucao_mensal['mes_criacao'].fillna(evolucao_mensal['mes_conclusao'])
            evolucao_mensal['OS Criadas'] = evolucao_mensal['OS Criadas'].fillna(0).astype(int)
            evolucao_mensal['OS Concluídas'] = evolucao_mensal['OS Concluídas'].fillna(0).astype(int)
            evolucao_mensal = evolucao_mensal[['Mês', 'OS Criadas', 'OS Concluídas']].sort_values('Mês')

            fig_evolucao = go.Figure()
            # AJUSTE 1: Adicionado o parâmetro 'text' para os rótulos de dados
            fig_evolucao.add_trace(go.Bar(x=evolucao_mensal['Mês'], y=evolucao_mensal['OS Criadas'], name='OS Criadas', marker_color='#1f77b4', opacity=0.7, text=evolucao_mensal['OS Criadas']))
            fig_evolucao.add_trace(go.Bar(x=evolucao_mensal['Mês'], y=evolucao_mensal['OS Concluídas'], name='OS Concluídas', marker_color='#2ca02c', opacity=0.7, text=evolucao_mensal['OS Concluídas']))
            
            fig_evolucao.update_traces(textposition='outside') # Posiciona os rótulos fora das barras
            fig_evolucao.update_layout(barmode='group', height=400, xaxis_tickangle=-45, xaxis_title="Mês", yaxis_title="Quantidade de OS")
            st.plotly_chart(fig_evolucao, use_container_width=True)

        # AJUSTE 2: Novo gráfico de evolução do backlog
        st.subheader("Evolução do Backlog (OS em Aberto)")
        try:
            # Preparando os dados para o cálculo do backlog
            criadas = df_filtrado[['Criado em']].copy()
            criadas['tipo'] = 1 # 1 para criação
            criadas.rename(columns={'Criado em': 'data'}, inplace=True)

            concluidas = df_filtrado[df_filtrado['data_conclusao'].notna()][['data_conclusao']].copy()
            concluidas['tipo'] = -1 # -1 para conclusão
            concluidas.rename(columns={'data_conclusao': 'data'}, inplace=True)

            # Combinando os eventos
            eventos = pd.concat([criadas, concluidas])
            eventos['data'] = eventos['data'].dt.date
            eventos_diarios = eventos.groupby('data')['tipo'].sum().reset_index()

            # Criando um range de datas completo para garantir a continuidade
            date_range = pd.date_range(start=eventos_diarios['data'].min(), end=eventos_diarios['data'].max(), freq='D')
            backlog_df = pd.DataFrame(date_range, columns=['data'])
            backlog_df['data'] = backlog_df['data'].dt.date

            # Juntando com os eventos e calculando o backlog cumulativo
            backlog_df = pd.merge(backlog_df, eventos_diarios, on='data', how='left').fillna(0)
            backlog_df['backlog'] = backlog_df['tipo'].cumsum()

            # Plotando o gráfico
            fig_backlog_evolucao = px.area(backlog_df, x='data', y='backlog', title="Evolução Diária do Backlog de OS")
            fig_backlog_evolucao.update_layout(height=400, xaxis_title="Data", yaxis_title="Quantidade de OS em Aberto")
            st.plotly_chart(fig_backlog_evolucao, use_container_width=True)
        except Exception as e:
            st.info(f"Não foi possível gerar o gráfico de evolução do backlog. Motivo: {e}")


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

    # Análise de Falhas
    st.header("🔧 Análise de Falhas")
    if 'order.id' in respostas_falhas.columns:
        falhas_filtradas = respostas_falhas[respostas_falhas['order.id'].isin(df_filtrado['id'])]
        if not falhas_filtradas.empty:
            col1, col2 = st.columns(2)
            with col1:
                falhas_counts = falhas_filtradas['value'].value_counts().head(10)
                fig_falhas = px.bar(x=falhas_counts.values, y=falhas_counts.index, orientation='h', title="Top 10 Falhas Mais Comuns", text=falhas_counts.values)
                fig_falhas.update_traces(textposition='outside', texttemplate='%{text}')
                fig_falhas.update_layout(height=500, xaxis_title="Quantidade", yaxis_title="Tipo de Falha", margin=dict(t=60, b=60, l=200, r=100), xaxis=dict(range=[0, falhas_counts.max() * 1.15 if not falhas_counts.empty else 10]))
                st.plotly_chart(fig_falhas, use_container_width=True)
            with col2:
                falhas_com_data = falhas_filtradas.merge(df_filtrado[['id', 'Criado em']], left_on='order.id', right_on='id')
                falhas_com_data['mes'] = falhas_com_data['Criado em'].dt.to_period('M').astype(str)
                falhas_por_mes = falhas_com_data.groupby('mes').size().reset_index(name='Quantidade de Falhas')
                fig_falhas_mes = px.line(falhas_por_mes, x='mes', y='Quantidade de Falhas', title="Evolução de Falhas por Mês", markers=True)
                fig_falhas_mes.update_traces(text=falhas_por_mes['Quantidade de Falhas'], textposition='top center')
                fig_falhas_mes.update_layout(height=500, xaxis_tickangle=-45, margin=dict(t=60, b=100, l=60, r=60))
                st.plotly_chart(fig_falhas_mes, use_container_width=True)

            st.subheader("📊 Estatísticas de Falhas")
            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Total de Falhas Reportadas", len(falhas_filtradas))
            with col2: st.metric("OS com Falhas", falhas_filtradas['order.id'].nunique())
            with col3:
                if total_os > 0:
                    percentual_os_com_falhas = (falhas_filtradas['order.id'].nunique() / total_os) * 100
                    st.metric("% OS com Falhas", f"{percentual_os_com_falhas:.1f}%")
            with col4: st.metric("Tipos de Falhas Únicos", falhas_filtradas['value'].nunique())
        else:
            st.info("Nenhuma falha encontrada para as OS filtradas.")
    else:
        st.warning("Coluna 'order.id' não encontrada na tabela de respostas.")

    # Tabela resumo
    st.header("📋 Tabela Resumo das OS")
    if not df_filtrado.empty:
        df_display = df_filtrado[[
            'Numero OS', 'Cliente', 'Cliente - Estado', 'Criado em',
            'status_final', 'data_conclusao', 'os_concluida', 'link'
        ]].copy()
        df_display['Criado em'] = df_display['Criado em'].apply(lambda x: x.strftime('%d/%m/%Y %H:%M') if pd.notna(x) else 'N/A')
        df_display['data_conclusao'] = df_display['data_conclusao'].apply(lambda x: x.strftime('%d/%m/%Y %H:%M') if pd.notna(x) else 'N/A')
        df_display['os_concluida'] = df_display['os_concluida'].map({True: '✅ Sim', False: '❌ Não'})
        df_display.columns = ['Número OS', 'Cliente', 'Estado', 'Criado em', 'Status Final', 'Data Conclusão', 'Concluída', 'link']

        st.dataframe(
            df_display,
            use_container_width=True,
            column_config={"link": st.column_config.LinkColumn("Relatório", help="Clique para abrir o relatório.", display_text="📄")},
            hide_index=True
        )

        @st.cache_data
        def to_excel(df):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='OS_Filtradas')
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
