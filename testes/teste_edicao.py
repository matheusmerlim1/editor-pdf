# -*- coding: utf-8 -*-
"""Teste automatizado do nucleo de edicao (nao abre a interface grafica).

Cria um PDF, extrai os trechos de texto, substitui alguns deles, grava o
resultado e confere se o texto novo, a formatacao e os desenhos da pagina
sobreviveram. Uso:  python testes/teste_edicao.py
"""

import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from editor_pdf import EditorPDF, mapear_fonte, normalizar_texto


def criar_pdf(caminho):
    doc = fitz.open()
    pagina = doc.new_page()
    pagina.insert_text((72, 100), "Relatorio de Manutencao",
                       fontname="hebo", fontsize=18, color=(0.1, 0.2, 0.6))
    pagina.insert_text((72, 140), "Responsavel: Joao da Silva",
                       fontname="helv", fontsize=12)
    pagina.insert_text((72, 160), "Situacao: pendente",
                       fontname="tiit", fontsize=11, color=(0.6, 0, 0))
    pagina.insert_text((72, 180), "codigo = ABC-123", fontname="cour", fontsize=10)
    pagina.draw_rect(fitz.Rect(60, 80, 400, 200), color=(0, 0, 0), width=0.7)
    doc.save(caminho)
    doc.close()


def main():
    falhas = []

    def conferir(condicao, descricao):
        print(("  ok   " if condicao else "  FALHA") + "  " + descricao)
        if not condicao:
            falhas.append(descricao)

    print("Mapeamento de fontes:")
    conferir(mapear_fonte("Arial-BoldMT", 0) == "hebo", "Arial Bold -> hebo")
    conferir(mapear_fonte("TimesNewRoman", 0) == "tiro", "Times -> tiro")
    conferir(mapear_fonte("Consolas", 0) == "cour", "Consolas -> cour")
    conferir(mapear_fonte("Qualquer", (1 << 4) | (1 << 1)) == "hebi",
             "flags negrito+italico -> hebi")
    conferir(normalizar_texto(u"a — b “c”") == 'a - b "c"',
             "normalizacao de travessao e aspas curvas")

    pasta = tempfile.mkdtemp(prefix="teste_editor_pdf_")
    origem = os.path.join(pasta, "original.pdf")
    destino = os.path.join(pasta, "editado.pdf")
    criar_pdf(origem)

    print("\nExtracao do texto:")
    doc = fitz.open(origem)
    pagina = doc[0]
    trechos = EditorPDF.extrair_trechos(EditorPDF, pagina)
    conferir(len(trechos) == 4, "4 trechos identificados (obtidos: %d)" % len(trechos))
    conferir(trechos[0]["text"] == "Relatorio de Manutencao", "texto do 1o trecho")
    conferir(abs(trechos[0]["size"] - 18) < 0.1, "tamanho do 1o trecho = 18")
    conferir(trechos[0]["base14"] == "hebo", "estilo negrito reconhecido")
    conferir(trechos[2]["base14"] == "tiit", "estilo italico com serifa reconhecido")

    print("\nSubstituicao:")
    novos_textos = [
        u"Relatório de Manutenção Predial",
        u"Responsável: Matheus Merlim",
    ]
    EditorPDF.substituir_trechos(EditorPDF, pagina,
                                 [(trechos[0], novos_textos[0]),
                                  (trechos[1], novos_textos[1])])
    doc.save(destino, garbage=4, deflate=True)
    doc.close()

    doc = fitz.open(destino)
    resultado = EditorPDF.extrair_trechos(EditorPDF, doc[0])
    texto_completo = doc[0].get_text()
    por_texto = dict((t["text"], t) for t in resultado)

    conferir(novos_textos[0] in texto_completo, "texto novo do titulo gravado")
    conferir(novos_textos[1] in texto_completo, "texto novo do responsavel gravado")
    conferir("Joao da Silva" not in texto_completo, "texto antigo removido")
    conferir("Situacao: pendente" in texto_completo, "trecho nao editado preservado")
    conferir("codigo = ABC-123" in texto_completo, "trecho monoespacado preservado")
    conferir(len(resultado) == 4, "continuam 4 trechos (obtidos: %d)" % len(resultado))
    conferir(abs(por_texto[novos_textos[0]]["size"] - 18) < 0.1, "tamanho mantido")
    conferir(por_texto[novos_textos[0]]["base14"] == "hebo", "negrito mantido")
    conferir(por_texto[novos_textos[0]]["rgb"][2] > 0.5, "cor azul mantida")
    conferir(len(doc[0].get_drawings()) >= 1, "desenho vetorial preservado")

    print("\nAjuste de tamanho:")
    grande = EditorPDF.tamanho_que_cabe("x" * 400, "helv", 18, 400)
    conferir(grande < 18, "fonte reduzida quando o texto nao cabe")
    igual = EditorPDF.tamanho_que_cabe("ok", "helv", 12, 400)
    conferir(igual == 12, "fonte mantida quando o texto cabe")
    doc.close()

    print("\n" + "-" * 52)
    if falhas:
        print("%d verificacao(oes) falharam:" % len(falhas))
        for f in falhas:
            print("  -", f)
        sys.exit(1)
    print("Todos os testes passaram.")


if __name__ == "__main__":
    main()
