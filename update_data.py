# update_data.py

# 1. Importa todos os seus scripts de geração de dados
import baseOs
import atividades
import equipamentosOs
import formularios
import respostas
import orcamentos

def main():
    print("Iniciando a atualização dos dados...")

    # 2. Roda a função principal de cada script, em sequência
    baseOs.gerar_arquivo_ordens()
    print("✅ Arquivo 'ordens_de_servico.xlsx' atualizado.")

    atividades.gerar_arquivo_atividades()
    print("✅ Arquivo 'atividades.xlsx' atualizado.")

    equipamentosOs.gerar_arquivo_equipamentos()
    # CORREÇÃO: Mensagem de log ajustada para o arquivo correto
    print("✅ Arquivo 'tabela_equipamentos.xlsx' atualizado.")

    # CORREÇÃO: Corrigido o erro de digitação de 'fomularios' para 'formularios'
    formularios.gerar_arquivo_formularios()
    # CORREÇÃO: Mensagem de log ajustada para o arquivo correto
    print("✅ Arquivo 'formularios.xlsx' atualizado.") # Ajuste o nome do arquivo se for diferente

    respostas.gerar_arquivo_respostas()
    # CORREÇÃO: Mensagem de log ajustada para o arquivo correto
    print("✅ Arquivo 'tabela_respostas.xlsx' atualizado.")

    orcamentos.gerar_arquivo_orcamentos()
    # CORREÇÃO: Mensagem de log ajustada para o arquivo correto
    print("✅ Arquivo 'orcamentos.xlsx' atualizado.") # Ajuste o nome do arquivo se for diferente

    print("\n🎉 Todos os arquivos de dados foram atualizados com sucesso!")

if __name__ == "__main__":
    main()

