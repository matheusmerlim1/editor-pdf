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

    doc.close()

    print("\nO corpo da fonte precisa ser mantido, mesmo com texto bem maior:")
    origem = os.path.join(pasta, "corpo.pdf")
    saida = os.path.join(pasta, "corpo_editado.pdf")
    d = fitz.open()
    p1 = d.new_page()
    p1.insert_text((60, 100), "Nome: Joao", fontname="helv", fontsize=12)
    p1.insert_text((420, 140), "pendente", fontname="helv", fontsize=10)   # coluna a direita
    p1.insert_text((60, 180), "Titulo", fontname="hebo", fontsize=20)
    d.save(origem)
    d.close()

    d = fitz.open(origem)
    pagina = d[0]
    antes = EditorPDF.extrair_trechos(EditorPDF, pagina)
    longos = [
        "Nome: Joao Pedro da Silva Oliveira Santos Ferreira Costa Almeida Rodrigues Nascimento",
        "aguardando conferencia do setor responsavel pela manutencao predial",
        "Titulo bem mais comprido do que o original para forcar o transbordo",
    ]
    transbordaram = EditorPDF.substituir_trechos(EditorPDF, pagina, list(zip(antes, longos)))
    d.save(saida, garbage=4, deflate=True)
    d.close()

    d = fitz.open(saida)
    # O texto que passa da margem fica fora da area visivel e a extracao o
    # devolve cortado, por isso a comparacao e feita pelo inicio do texto.
    obtidos = EditorPDF.extrair_trechos(EditorPDF, d[0])

    def achar(texto):
        for t in obtidos:
            if texto.startswith(t["text"][:20]):
                return t
        return None

    for esperado, texto in zip([12.0, 10.0, 20.0], longos):
        achado = achar(texto)
        conferir(achado is not None and abs(achado["size"] - esperado) < 0.01,
                 "corpo %.1f mantido em %r" % (esperado, texto[:32]))
    conferir(achar(longos[2])["base14"] == "hebo", "negrito mantido no texto longo")
    # o 1o texto ainda cabe (482 de 530 pt); os outros dois passam da margem
    conferir(transbordaram == 2,
             "os 2 transbordos foram sinalizados (obtidos: %d)" % transbordaram)
    d.close()

    print("\nLinha justificada: o espacamento entre palavras deve ser preservado:")
    origem = os.path.join(pasta, "justificado.pdf")
    saida = os.path.join(pasta, "justificado_editado.pdf")
    paragrafo = ("3480 horas, em regime modular. Reconhecimento renovado nos termos da "
                 "Portaria MEC no 913, de 27/12/2018, publicada no D.O.U. no 249, Secao 1, "
                 "Pag. 134 a 141 de 28/12/2018. Resolucao No 2, de 20 de dezembro de 2019")
    d = fitz.open()
    d.new_page().insert_textbox(fitz.Rect(60, 90, 535, 180), paragrafo,
                                fontname="helv", fontsize=10,
                                align=fitz.TEXT_ALIGN_JUSTIFY)
    d.save(origem)
    d.close()

    d = fitz.open(origem)
    linha = EditorPDF.extrair_trechos(EditorPDF, d[0])[0]
    largura_antes = linha["bbox"][2] - linha["bbox"][0]
    natural = fitz.get_text_length(linha["text"], fontname=linha["base14"],
                                   fontsize=linha["size"])
    conferir(largura_antes - natural > 5,
             "a linha de teste esta mesmo justificada (%.1f pt de folga)"
             % (largura_antes - natural))

    EditorPDF.substituir_trechos(
        EditorPDF, d[0],
        [(linha, linha["text"].replace("Reconhecimento", "Reconhecimentos"))])
    d.save(saida, garbage=4, deflate=True)
    d.close()

    d = fitz.open(saida)
    editada = [t for t in EditorPDF.extrair_trechos(EditorPDF, d[0])
               if "Reconhecimentos" in t["text"]]
    conferir(len(editada) == 1,
             "a linha continua sendo um unico trecho (obtidos: %d)" % len(editada))
    if editada:
        largura_depois = editada[0]["bbox"][2] - editada[0]["bbox"][0]
        conferir(abs(largura_depois - largura_antes) < 2,
                 "a linha manteve a largura: %.1f -> %.1f pt"
                 % (largura_antes, largura_depois))
        conferir(abs(editada[0]["size"] - linha["size"]) < 0.01, "o corpo continua o mesmo")
    d.close()


    print("\nDeteccao de transbordo:")
    conferir(EditorPDF.passa_da_margem("x" * 400, "helv", 18, 400) is True,
             "texto comprido e sinalizado")
    conferir(EditorPDF.passa_da_margem("ok", "helv", 12, 400) is False,
             "texto curto nao e sinalizado")

    print("\n" + "-" * 52)
    if falhas:
        print("%d verificacao(oes) falharam:" % len(falhas))
        for f in falhas:
            print("  -", f)
        sys.exit(1)
    print("Todos os testes passaram.")


if __name__ == "__main__":
    main()
