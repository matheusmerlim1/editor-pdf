# -*- coding: utf-8 -*-
"""Gera um PDF de exemplo para testar o Editor de PDF.

Uso:  python exemplos/gerar_exemplo.py
Saida: exemplos/documento_exemplo.pdf
"""

import os

try:
    import pymupdf as fitz
except ImportError:
    import fitz

SAIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documento_exemplo.pdf")

AZUL = (0.09, 0.16, 0.32)
CINZA = (0.35, 0.38, 0.45)
VERMELHO = (0.70, 0.12, 0.14)


def main():
    doc = fitz.open()
    pagina = doc.new_page()          # A4 retrato (595 x 842)

    # cabecalho
    pagina.draw_rect(fitz.Rect(0, 0, 595, 90), color=None, fill=AZUL)
    pagina.insert_text((56, 46), "CEFET - Sistema de Informacao",
                       fontname="hebo", fontsize=17, color=(1, 1, 1))
    pagina.insert_text((56, 68), "Relatorio de Atividades - 2o semestre",
                       fontname="helv", fontsize=10, color=(0.80, 0.85, 0.95))

    # corpo
    linhas = [
        ("Titulo do projeto: Editor de PDF em Python", "hebo", 13, AZUL),
        ("Aluno responsavel: Matheus Merlim", "helv", 11, (0, 0, 0)),
        ("Disciplina: Linguagem de Programacao", "helv", 11, (0, 0, 0)),
        ("Data de entrega: 02/09/2026", "helv", 11, (0, 0, 0)),
        ("Situacao: em andamento", "tibo", 11, VERMELHO),
    ]
    y = 140
    for texto, fonte, corpo, cor in linhas:
        pagina.insert_text((56, y), texto, fontname=fonte, fontsize=corpo, color=cor)
        y += 26

    pagina.insert_text((56, y + 14), "Resumo", fontname="hebo", fontsize=12, color=AZUL)
    resumo = (
        "O trabalho consiste em um aplicativo de mesa capaz de abrir um arquivo PDF, "
        "identificar os trechos de texto presentes no documento, permitir a edicao "
        "desses trechos e gravar novamente o resultado em formato PDF, preservando "
        "a posicao, o tamanho, a cor e o estilo originais de cada trecho."
    )
    pagina.insert_textbox(fitz.Rect(56, y + 26, 539, y + 120), resumo,
                          fontname="tiro", fontsize=11, color=(0.1, 0.1, 0.1), align=3)

    # tabela simples
    topo = y + 140
    pagina.insert_text((56, topo), "Etapas", fontname="hebo", fontsize=12, color=AZUL)
    etapas = [
        ("1", "Leitura do PDF e extracao do texto", "concluida"),
        ("2", "Interface grafica de edicao", "concluida"),
        ("3", "Gravacao do arquivo editado", "concluida"),
        ("4", "Geracao do executavel", "em andamento"),
    ]
    ly = topo + 18
    pagina.draw_line(fitz.Point(56, ly), fitz.Point(539, ly), color=CINZA, width=0.8)
    ly += 16
    for num, descricao, situacao in etapas:
        pagina.insert_text((60, ly), num, fontname="cour", fontsize=10, color=CINZA)
        pagina.insert_text((90, ly), descricao, fontname="helv", fontsize=10, color=(0, 0, 0))
        pagina.insert_text((420, ly), situacao, fontname="heit", fontsize=10, color=CINZA)
        ly += 20
    pagina.draw_line(fitz.Point(56, ly - 6), fitz.Point(539, ly - 6), color=CINZA, width=0.8)

    # rodape
    pagina.insert_text((56, 800), "Documento gerado automaticamente para teste do Editor de PDF.",
                       fontname="heit", fontsize=8, color=CINZA)

    doc.save(SAIDA, garbage=4, deflate=True)
    doc.close()
    print("PDF de exemplo criado em:", SAIDA)


if __name__ == "__main__":
    main()
