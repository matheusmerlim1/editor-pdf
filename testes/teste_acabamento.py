# -*- coding: utf-8 -*-
"""Teste automatizado do acabamento do documento (nao abre a interface grafica).

Numeracao, carimbo, papel timbrado, capa e anexo, propriedades, protecao por
senha, imagens em PDF e exportacao como imagem. Uso:
    python testes/teste_acabamento.py
"""

import datetime
import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import acabamento as ac


def documento(paginas=3, rotacoes=None):
    doc = fitz.open()
    for i in range(paginas):
        p = doc.new_page()
        p.insert_text((72, 100), "Conteudo da pagina %d" % (i + 1), fontsize=12)
        if rotacoes:
            p.set_rotation(rotacoes[i])
    return doc


def linhas(pagina):
    """(texto, caixa na pagina visivel, direcao na pagina visivel) de cada linha."""
    giro = pagina.rotation_matrix
    saida = []
    for bloco in pagina.get_text("dict")["blocks"]:
        for linha in bloco.get("lines", []):
            texto = "".join(s["text"] for s in linha["spans"])
            caixa = fitz.Rect(linha["bbox"]) * giro
            direcao = fitz.Point(linha["dir"]) * fitz.Matrix(pagina.rotation)
            saida.append((texto, caixa.normalize(), direcao))
    return saida


def achar(pagina, trecho):
    for texto, caixa, direcao in linhas(pagina):
        if trecho in texto:
            return texto, caixa, direcao
    return None


def main():
    falhas = []

    def conferir(condicao, descricao):
        print(("  ok   " if condicao else "  FALHA") + "  " + descricao)
        if not condicao:
            falhas.append(descricao)

    pasta = tempfile.mkdtemp(prefix="teste_acabamento_")

    print("Marcadores:")
    ctx = {"pagina": "3", "paginas": "10", "titulo": "Relatorio"}
    conferir(ac.substituir_marcadores("<Pagina> de <Paginas>", ctx) == "3 de 10",
             "<Pagina> e <Paginas> trocados")
    conferir(ac.substituir_marcadores("<página>/<PAGINAS>", ctx) == "3/10",
             "acento e maiusculas ignorados")
    conferir(ac.substituir_marcadores("<Titulo> <x>", ctx) == "Relatorio <x>",
             "marcador desconhecido fica como esta")
    doc = documento(2)
    c = ac.contexto_do_documento(doc, r"C:\pasta\contrato final.pdf",
                                 datetime.datetime(2026, 3, 9, 14, 5))
    conferir(c["arquivo"] == "contrato final" and c["titulo"] == "contrato final",
             "nome do arquivo vira titulo quando o PDF nao tem um")
    conferir(c["data"] == "09/03/2026" and c["hora"] == "14:05", "data e hora formatadas")
    conferir([ac.romano(n) for n in (1, 4, 9, 14, 40, 2026)] ==
             ["i", "iv", "ix", "xiv", "xl", "mmxxvi"], "numeros romanos")

    print("\nNumeracao de paginas:")
    doc = documento(4)
    n = ac.numerar_paginas(doc, posicao="inferior-centro")
    conferir(n == 4, "4 paginas numeradas (obtidas: %d)" % n)
    texto, caixa, _ = achar(doc[1], "2 de 4")
    largura = doc[1].rect.width
    conferir(abs((caixa.x0 + caixa.x1) / 2 - largura / 2) < 2, "numero centralizado")
    conferir(caixa.y1 > doc[1].rect.height - 40, "numero no rodape")

    doc = documento(4)
    ac.numerar_paginas(doc, formato="Pag. <Pagina>", posicao="inferior-direita",
                       a_partir_da_pagina=2, primeiro_numero=1, alternar=True)
    conferir(achar(doc[0], "Pag.") is None, "a capa ficou sem numero")
    _, impar, _ = achar(doc[2], "Pag. 2")      # 3a folha, numero 2
    _, par, _ = achar(doc[1], "Pag. 1")        # 2a folha, numero 1
    conferir(par.x0 < 100, "pagina par: numero espelhado para a esquerda")
    conferir(impar.x1 > largura - 100, "pagina impar: numero a direita")

    doc = documento(3)
    ac.numerar_paginas(doc, formato="<Pagina>", romanos=True)
    conferir(achar(doc[2], "iii") is not None, "numeracao em romanos")

    doc = documento(3, rotacoes=[0, 90, 270])
    ac.numerar_paginas(doc, posicao="inferior-direita")
    for i in (1, 2):
        pagina = doc[i]
        _, caixa, direcao = achar(pagina, "%d de 3" % (i + 1))
        conferir(caixa.y1 > pagina.rect.height - 40 and caixa.x1 > pagina.rect.width - 60,
                 "pagina girada %d graus: numero no canto inferior direito" % pagina.rotation)
        conferir(direcao.x > 0.99, "pagina girada %d graus: numero na horizontal"
                 % pagina.rotation)

    print("\nCarimbo:")
    doc = documento(2, rotacoes=[0, 90])
    feitas = ac.carimbar(doc, "CONFIDENCIAL")
    conferir(feitas == 2, "2 paginas carimbadas")
    for pagina in doc:
        achado = achar(pagina, "CONFIDENCIAL")
        conferir(achado is not None, "pagina %d: carimbo gravado inteiro" % (pagina.number + 1))
        if achado:
            _, caixa, direcao = achado
            centro = pagina.rect.width / 2, pagina.rect.height / 2
            conferir(abs((caixa.x0 + caixa.x1) / 2 - centro[0]) < 15 and
                     abs((caixa.y0 + caixa.y1) / 2 - centro[1]) < 15,
                     "pagina %d: carimbo no centro" % (pagina.number + 1))
            conferir(direcao.x > 0.3 and direcao.y < -0.3,
                     "pagina %d: carimbo subindo na diagonal" % (pagina.number + 1))
            conferir(caixa.x0 > -1 and caixa.x1 < pagina.rect.width + 1,
                     "pagina %d: carimbo dentro da pagina" % (pagina.number + 1))
    conferir(b"/ca 0.35" in doc.tobytes() or b"/ca .35" in doc.tobytes(),
             "carimbo semitransparente")

    print("\nPapel timbrado:")
    fundo = fitz.open()
    for rotulo in ("TIMBRE 1", "TIMBRE 2"):
        fundo.new_page().insert_text((40, 40), rotulo, fontsize=14)
    for repeticao, esperado in (("ultima", ["TIMBRE 1", "TIMBRE 2", "TIMBRE 2", "TIMBRE 2"]),
                                ("todas", ["TIMBRE 1", "TIMBRE 2", "TIMBRE 1", "TIMBRE 2"]),
                                ("nenhuma", ["TIMBRE 1", "TIMBRE 2", None, None])):
        doc = documento(4)
        ac.aplicar_fundo(doc, fundo, repeticao=repeticao)
        obtido = []
        for pagina in doc:
            achado = achar(pagina, "TIMBRE")
            obtido.append(achado[0] if achado else None)
        conferir(obtido == esperado, "repeticao %r: %s" % (repeticao, obtido))
    doc = documento(1)
    ac.aplicar_fundo(doc, fundo)
    conferir("Conteudo da pagina 1" in doc[0].get_text(), "o conteudo original continua")
    doc = documento(1, rotacoes=[90])
    ac.aplicar_fundo(doc, fundo)
    _, caixa, direcao = achar(doc[0], "TIMBRE 1")
    conferir(caixa.y0 < 80 and direcao.x > 0.99,
             "pagina girada: timbrado no alto e de pe para quem le")

    print("\nCapa e anexo:")
    doc = documento(2)
    capa = fitz.open()
    capa.new_page().insert_text((72, 72), "CAPA", fontsize=20)
    anexo = documento(3)
    ac.inserir_capa(doc, capa)
    ac.anexar_ao_final(doc, anexo)
    conferir(doc.page_count == 6, "6 paginas no total (obtidas: %d)" % doc.page_count)
    conferir("CAPA" in doc[0].get_text(), "capa na frente")
    conferir("Conteudo da pagina 1" in doc[1].get_text(), "documento logo depois da capa")
    conferir("Conteudo da pagina 3" in doc[5].get_text(), "anexo no final")

    print("\nPropriedades:")
    doc = documento(1)
    ac.definir_propriedades(doc, titulo="Laudo <Arquivo>", autor="Matheus",
                            palavras_chave="laudo, vistoria",
                            caminho=os.path.join(pasta, "obra 12.pdf"))
    destino = os.path.join(pasta, "propriedades.pdf")
    doc.save(destino)
    meta = fitz.open(destino).metadata
    conferir(meta["title"] == "Laudo obra 12", "titulo com marcador gravado")
    conferir(meta["author"] == "Matheus", "autor gravado")
    conferir(meta["keywords"] == "laudo, vistoria", "palavras-chave gravadas")
    conferir(meta["creator"] == "Editor de PDF", "programa criador registrado")

    print("\nProtecao por senha:")
    try:
        ac.opcoes_de_protecao("")
        conferir(False, "sem senha do dono deve dar erro")
    except ValueError:
        conferir(True, "sem senha do dono da erro")
    doc = documento(1)
    destino = os.path.join(pasta, "protegido.pdf")
    doc.save(destino, **ac.opcoes_de_protecao("dono123", "abre123", imprimir=True, copiar=False))
    protegido = fitz.open(destino)
    conferir(protegido.needs_pass, "o arquivo pede senha para abrir")
    conferir(not protegido.authenticate("errada"), "senha errada recusada")
    conferir(protegido.authenticate("abre123") > 0, "senha de abrir aceita")
    perm = protegido.permissions
    conferir(bool(perm & fitz.PDF_PERM_PRINT), "impressao liberada")
    conferir(not perm & fitz.PDF_PERM_COPY, "copia bloqueada")
    conferir("Conteudo da pagina 1" in protegido[0].get_text(), "conteudo legivel com a senha")
    conferir("AES" in (protegido.metadata.get("encryption") or ""), "criptografia AES")

    print("\nImagens em PDF e PDF em imagens:")
    from PIL import Image
    caminhos = []
    for i, tamanho in enumerate(((300, 200), (200, 400))):
        caminho = os.path.join(pasta, "imagem%d.png" % i)
        Image.new("RGB", tamanho, (200, 40 * i, 40)).save(caminho, dpi=(72, 72))
        caminhos.append(caminho)
    convertido = ac.imagens_para_pdf(caminhos)
    conferir(convertido.page_count == 2, "uma pagina por imagem")
    conferir(abs(convertido[1].rect.width - 200) < 1 and abs(convertido[1].rect.height - 400) < 1,
             "pagina com o tamanho da imagem")

    doc = documento(3)
    criados = ac.exportar_imagens(doc, pasta, "folha", formato="png", dpi=72)
    conferir(len(criados) == 3 and all(os.path.exists(c) for c in criados), "3 PNGs criados")
    conferir(os.path.basename(criados[0]) == "folha_001.png", "nome numerado")
    conferir(Image.open(criados[0]).size == (595, 842), "PNG em 72 dpi = tamanho em pontos")
    jpgs = ac.exportar_imagens(doc, pasta, "folha", formato="jpg", dpi=50, paginas=[1])
    conferir(len(jpgs) == 1 and jpgs[0].endswith("_002.jpg"), "JPEG so da pagina escolhida")
    tif = ac.exportar_imagens(doc, pasta, "folha", formato="tif", dpi=50)
    quadros = Image.open(tif[0]).n_frames if tif else 0
    conferir(len(tif) == 1 and quadros == 3, "TIFF unico com 3 paginas (obtidas: %d)" % quadros)

    print("\nImagens em folha de tamanho fixo:")
    largo = os.path.join(pasta, "largo.png")
    Image.new("RGB", (900, 300), (10, 120, 60)).save(largo)
    a4 = ac.imagens_para_pdf([largo, caminhos[1]], tamanho="a4", margem=20)
    conferir([tuple(round(v) for v in p.rect[2:]) for p in a4] == [(842, 595), (595, 842)],
             "folha A4 deitada para imagem larga e em pe para imagem alta")
    caixa = fitz.Rect(a4[0].get_image_info()[0]["bbox"])
    conferir(abs(caixa.width - 802) < 1 and abs(caixa.height / caixa.width - 1 / 3) < 0.01,
             "imagem ocupa a largura util sem distorcer")
    retrato = ac.imagens_para_pdf([largo], tamanho="carta", orientacao="retrato")
    conferir(tuple(round(v) for v in retrato[0].rect[2:]) == (612, 792), "orientacao forcada")

    print("\nOtimizar tamanho:")
    import random
    random.seed(1)
    ruido = Image.frombytes("RGB", (1600, 1600), bytes(random.getrandbits(8) for _ in range(1600 * 1600 * 3)))
    pesada = os.path.join(pasta, "pesada.png")
    ruido.save(pesada)
    doc = documento(1)
    doc[0].insert_image(fitz.Rect(72, 150, 272, 350), filename=pesada)   # ~576 dpi
    antes, depois = ac.otimizar_tamanho(doc, "media")
    conferir(depois < antes / 4, "arquivo encolheu: %d -> %d KB" % (antes // 1024, depois // 1024))
    info = doc[0].get_image_info()[0]
    # o MuPDF reduz por fatores de 2, entao o resultado fica perto do alvo, nao exato
    conferir(info["width"] < 1600, "imagem reamostrada (1600 -> %d px)" % info["width"])
    conferir("Conteudo da pagina 1" in doc[0].get_text(), "texto intacto")

    print("\nConverter cores:")
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 100), "vermelho", color=(1, 0, 0), fontsize=14)
    p.insert_image(fitz.Rect(72, 150, 172, 200), filename=caminhos[0])
    ac.converter_cores(doc, "cinza")
    span = doc[0].get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
    r, g, b = fitz.sRGB_to_pdf(span["color"])
    conferir(abs(r - g) < 0.01 and abs(g - b) < 0.01, "texto vermelho virou cinza")
    pix = fitz.Pixmap(doc, doc[0].get_images()[0][0])
    conferir(pix.n - pix.alpha == 1, "imagem virou tons de cinza")

    print("\nVisualizacao ao abrir:")
    doc = documento(3)
    ac.definir_visualizacao(doc, layout="duas_paginas_impar_direita", painel="miniaturas",
                            pagina_inicial=2)
    catalogo = doc.pdf_catalog()
    conferir(doc.xref_get_key(catalogo, "PageLayout")[1] == "/TwoPageRight", "layout gravado")
    conferir(doc.xref_get_key(catalogo, "PageMode")[1] == "/UseThumbs", "painel gravado")
    conferir(doc.xref_get_key(catalogo, "OpenAction")[1].startswith("[%d 0 R" % doc.page_xref(1)),
             "abre na pagina 2")
    ac.definir_visualizacao(doc)
    conferir(doc.xref_get_key(catalogo, "PageLayout")[0] == "null" and
             doc.xref_get_key(catalogo, "OpenAction")[0] == "null", "padrao limpa as escolhas")

    print("\nExportar texto:")
    doc = documento(2)
    destino = os.path.join(pasta, "texto.txt")
    n = ac.exportar_texto(doc, destino)
    conteudo = open(destino, encoding="utf-8").read()
    conferir(n > 0 and "Conteudo da pagina 1" in conteudo and "Conteudo da pagina 2" in conteudo,
             "texto das duas paginas gravado")
    conferir(conteudo.count("\f") == 1, "quebra de pagina entre elas")

    print("\n" + "-" * 52)
    if falhas:
        print("%d verificacao(oes) falharam:" % len(falhas))
        for f in falhas:
            print("  -", f)
        sys.exit(1)
    print("Todos os testes passaram.")


if __name__ == "__main__":
    main()
