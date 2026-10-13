# -*- coding: utf-8 -*-
"""
Acabamento do documento
=======================
Operacoes aplicadas ao PDF inteiro, depois (ou no lugar) da edicao do texto:
numeracao de paginas, carimbo, papel timbrado, capa e anexos, propriedades,
protecao por senha, conversao de imagens em PDF e exportacao das paginas como
imagem.

A lista de recursos segue as "acoes" que o PDFCreator (pdfforge) aplica ao
arquivo que ele gera. O codigo aqui e proprio, escrito sobre o PyMuPDF; do
PDFCreator vieram as ideias e o comportamento esperado de cada acao - por
exemplo, o carimbo na diagonal da pagina, a numeracao que pode alternar de
canto em paginas pares e o fundo que se repete a partir da ultima pagina.

Todas as funcoes recebem um fitz.Document ja aberto e o alteram no lugar, sem
interface grafica, para que possam ser testadas (testes/teste_acabamento.py).
"""

import datetime
import math
import os
import re
import unicodedata

try:
    import pymupdf as fitz
except ImportError:  # compatibilidade com versoes antigas do PyMuPDF
    import fitz


# --------------------------------------------------------------------------
# Marcadores (tokens)
# --------------------------------------------------------------------------
# Como os <Title>, <Author> e <DateTime> do PDFCreator: escritos entre sinais
# de menor e maior em qualquer texto de acabamento, sao trocados pelo valor
# correspondente na hora de aplicar. Acentos e maiusculas sao ignorados, entao
# <Pagina> e <página> dao no mesmo.
MARCADORES = {
    "pagina": "numero da pagina",
    "paginas": "total de paginas",
    "titulo": "titulo do documento",
    "autor": "autor do documento",
    "assunto": "assunto do documento",
    "arquivo": "nome do arquivo, sem a extensao",
    "data": "data de hoje (dd/mm/aaaa)",
    "hora": "hora atual (hh:mm)",
}


def _sem_acento(texto):
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower()


def contexto_do_documento(doc, caminho=None, agora=None):
    """Valores dos marcadores que nao dependem da pagina."""
    agora = agora or datetime.datetime.now()
    meta = doc.metadata or {}
    arquivo = os.path.splitext(os.path.basename(caminho))[0] if caminho else ""
    return {
        "titulo": meta.get("title") or arquivo,
        "autor": meta.get("author") or "",
        "assunto": meta.get("subject") or "",
        "arquivo": arquivo,
        "paginas": str(doc.page_count),
        "data": agora.strftime("%d/%m/%Y"),
        "hora": agora.strftime("%H:%M"),
    }


def substituir_marcadores(texto, contexto):
    """Troca cada <marcador> conhecido pelo seu valor; os demais ficam como estao."""
    def trocar(achado):
        chave = _sem_acento(achado.group(1))
        return str(contexto[chave]) if chave in contexto else achado.group(0)
    return re.sub(r"<([^<>\s]{1,20})>", trocar, texto or "")


def para_latin1(texto):
    """As fontes base-14 so desenham o latino-1; o resto vira equivalente ou '?'."""
    trocas = {u"—": "-", u"–": "-", u"‘": "'", u"’": "'",
              u"“": '"', u"”": '"', u"…": "...", u"•": "-"}
    for origem, destino in trocas.items():
        texto = texto.replace(origem, destino)
    return texto.encode("latin-1", "replace").decode("latin-1")


def romano(numero):
    """1 -> 'i', 4 -> 'iv', 2026 -> 'mmxxvi' (minusculas, como em prefacios)."""
    if numero <= 0:
        return str(numero)
    valores = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
               (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))
    saida = []
    for valor, simbolo in valores:
        while numero >= valor:
            saida.append(simbolo)
            numero -= valor
    return "".join(saida)


# --------------------------------------------------------------------------
# Escrita na pagina visivel
# --------------------------------------------------------------------------
# page.rect e a pagina como ela aparece na tela (ja girada), mas o conteudo
# e escrito no sistema sem giro. As funcoes abaixo recebem coordenadas da
# pagina visivel e fazem a conversao, de modo que o texto saia sempre na
# horizontal para quem le, mesmo em paginas com /Rotate.
def _escrever_visivel(pagina, ponto, texto, angulo=0.0, **opcoes):
    """Escreve `texto` com a linha-base comecando em `ponto` (pagina visivel).

    `angulo` e o giro do texto em graus, no sentido anti-horario de quem le.
    """
    desgiro = pagina.derotation_matrix
    inicio = fitz.Point(ponto) * desgiro
    giro_total = (angulo + pagina.rotation) % 360
    if giro_total in (0, 90, 180, 270):
        pagina.insert_text(inicio, texto, rotate=int(giro_total), **opcoes)
    else:
        # giros quebrados usam "morph": uma matriz aplicada em torno do inicio
        pagina.insert_text(inicio, texto, morph=(inicio, fitz.Matrix(giro_total)), **opcoes)


# --------------------------------------------------------------------------
# Numeracao de paginas
# --------------------------------------------------------------------------
POSICOES = ("inferior-centro", "inferior-direita", "inferior-esquerda",
            "superior-centro", "superior-direita", "superior-esquerda")


def _espelhar(posicao):
    if posicao.endswith("direita"):
        return posicao.replace("direita", "esquerda")
    if posicao.endswith("esquerda"):
        return posicao.replace("esquerda", "direita")
    return posicao


def numerar_paginas(doc, formato="<Pagina> de <Paginas>", posicao="inferior-centro",
                    a_partir_da_pagina=1, primeiro_numero=1, romanos=False,
                    alternar=False, tamanho=10.0, cor=(0, 0, 0), fonte="helv",
                    margem_horizontal=36.0, margem_vertical=28.0, caminho=None):
    """Escreve o numero em cada pagina, a partir de `a_partir_da_pagina`.

    `primeiro_numero` e o numero escrito nessa primeira pagina numerada (util
    quando a capa nao conta). Com `alternar`, as paginas pares trocam o lado
    esquerdo pelo direito, como em um livro impresso frente e verso.
    Devolve quantas paginas receberam numero.
    """
    if posicao not in POSICOES:
        raise ValueError("posicao desconhecida: %r" % posicao)
    contexto = contexto_do_documento(doc, caminho)
    total = doc.page_count
    numeradas = 0
    numero = primeiro_numero
    for indice in range(max(0, a_partir_da_pagina - 1), total):
        pagina = doc[indice]
        lugar = _espelhar(posicao) if alternar and (indice + 1) % 2 == 0 else posicao
        contexto["pagina"] = romano(numero) if romanos else str(numero)
        texto = para_latin1(substituir_marcadores(formato, contexto))
        largura = fitz.get_text_length(texto, fontname=fonte, fontsize=tamanho)
        visivel = pagina.rect
        if lugar.endswith("esquerda"):
            x = visivel.x0 + margem_horizontal
        elif lugar.endswith("direita"):
            x = visivel.x1 - margem_horizontal - largura
        else:
            x = visivel.x0 + (visivel.width - largura) / 2
        if lugar.startswith("superior"):
            y = visivel.y0 + margem_vertical + tamanho * 0.75
        else:
            y = visivel.y1 - margem_vertical
        _escrever_visivel(pagina, (x, y), texto, fontname=fonte, fontsize=tamanho, color=cor)
        numeradas += 1
        numero += 1
    return numeradas


# --------------------------------------------------------------------------
# Carimbo
# --------------------------------------------------------------------------
def carimbar(doc, texto, tamanho=None, cor=(0.75, 0.1, 0.1), opacidade=0.35,
             contorno=False, angulo=None, fonte="hebo", paginas=None, caminho=None):
    """Escreve `texto` atravessando o centro de cada pagina (ex.: 'CONFIDENCIAL').

    Como no PDFCreator, o angulo padrao e a diagonal da pagina, de baixo a
    esquerda para cima a direita. Sem `tamanho`, o corpo e escolhido para o
    texto ocupar 70% dessa diagonal. Com `contorno`, as letras saem vazadas.
    `paginas` limita o carimbo a uma lista de indices (0 = primeira).
    Devolve quantas paginas foram carimbadas.
    """
    contexto = contexto_do_documento(doc, caminho)
    indices = range(doc.page_count) if paginas is None else paginas
    feitas = 0
    for indice in indices:
        pagina = doc[indice]
        contexto["pagina"] = str(indice + 1)
        conteudo = para_latin1(substituir_marcadores(texto, contexto)).strip()
        if not conteudo:
            continue
        visivel = pagina.rect
        diagonal = math.hypot(visivel.width, visivel.height)
        giro = math.degrees(math.atan2(visivel.height, visivel.width)) if angulo is None else angulo
        largura_unitaria = fitz.get_text_length(conteudo, fontname=fonte, fontsize=1)
        corpo = tamanho or min(200.0, 0.7 * diagonal / max(largura_unitaria, 0.01))
        largura = largura_unitaria * corpo

        # o ponto de partida fica antes do centro, ao longo da direcao do texto,
        # e um pouco abaixo dele, para o meio das letras cair no centro
        rad = math.radians(giro)
        centro = fitz.Point(visivel.x0 + visivel.width / 2, visivel.y0 + visivel.height / 2)
        recuo, desce = largura / 2, corpo * 0.35
        ponto = fitz.Point(centro.x - recuo * math.cos(rad) + desce * math.sin(rad),
                           centro.y + recuo * math.sin(rad) + desce * math.cos(rad))
        opcoes = dict(fontname=fonte, fontsize=corpo, fill_opacity=opacidade,
                      stroke_opacity=opacidade)
        if contorno:
            opcoes.update(render_mode=1, color=cor, border_width=0.02)
        else:
            opcoes.update(color=cor)
        _escrever_visivel(pagina, ponto, conteudo, angulo=giro, **opcoes)
        feitas += 1
    return feitas


# --------------------------------------------------------------------------
# Papel timbrado, capa e anexos
# --------------------------------------------------------------------------
REPETICOES = ("todas", "ultima", "nenhuma")


def aplicar_fundo(doc, fundo, repeticao="ultima", por_cima=False, a_partir_da_pagina=1):
    """Coloca as paginas de outro PDF atras (ou na frente) das paginas do documento.

    E o papel timbrado: a pagina 1 do fundo vai na pagina 1 do documento, a 2
    na 2, e assim por diante. Quando o fundo tem menos paginas, `repeticao`
    diz o que fazer com o resto - "ultima" repete a ultima pagina do fundo
    (timbrado de primeira pagina + papel de continuacao), "todas" recomeca do
    inicio e "nenhuma" deixa as demais sem fundo.
    Devolve quantas paginas receberam fundo.
    """
    if repeticao not in REPETICOES:
        raise ValueError("repeticao desconhecida: %r" % repeticao)
    if fundo.page_count == 0:
        return 0
    feitas = 0
    for posicao, indice in enumerate(range(max(0, a_partir_da_pagina - 1), doc.page_count)):
        if posicao < fundo.page_count:
            origem = posicao
        elif repeticao == "todas":
            origem = posicao % fundo.page_count
        elif repeticao == "ultima":
            origem = fundo.page_count - 1
        else:
            break
        pagina = doc[indice]
        # o fundo deve ficar de pe para quem le, por isso e girado junto
        # com a pagina e colocado sobre a area sem giro
        pagina.show_pdf_page(pagina.rect * pagina.derotation_matrix, fundo, origem,
                             overlay=por_cima, keep_proportion=False,
                             rotate=pagina.rotation)
        feitas += 1
    return feitas


def inserir_capa(doc, capa):
    """Poe todas as paginas de `capa` antes da primeira pagina do documento."""
    doc.insert_pdf(capa, start_at=0)
    return capa.page_count


def anexar_ao_final(doc, outro):
    """Acrescenta todas as paginas de `outro` depois da ultima pagina."""
    doc.insert_pdf(outro)
    return outro.page_count


# --------------------------------------------------------------------------
# Propriedades
# --------------------------------------------------------------------------
def definir_propriedades(doc, titulo=None, autor=None, assunto=None,
                         palavras_chave=None, caminho=None):
    """Grava titulo, autor, assunto e palavras-chave (aceitam marcadores).

    Campos passados como None ficam como estavam; texto vazio apaga o campo.
    """
    meta = dict(doc.metadata or {})
    contexto = contexto_do_documento(doc, caminho)
    for chave, valor in (("title", titulo), ("author", autor),
                         ("subject", assunto), ("keywords", palavras_chave)):
        if valor is not None:
            meta[chave] = substituir_marcadores(valor, contexto).strip()
    meta["creator"] = "Editor de PDF"
    meta["modDate"] = fitz.get_pdf_now()
    # chaves que o set_metadata nao aceita (ex.: 'format', 'encryption')
    aceitas = ("title", "author", "subject", "keywords", "creator",
               "producer", "creationDate", "modDate", "trapped")
    doc.set_metadata({k: v for k, v in meta.items() if k in aceitas and v is not None})


# --------------------------------------------------------------------------
# Protecao por senha
# --------------------------------------------------------------------------
def opcoes_de_protecao(senha_dono, senha_abrir="", imprimir=True, copiar=False,
                       alterar=False, anotar=False, formularios=True):
    """Parametros extras de doc.save() para gravar o PDF criptografado (AES-256).

    `senha_dono` libera tudo e e obrigatoria; `senha_abrir` (opcional) e pedida
    para abrir o arquivo. As permissoes valem para quem abre sem a senha do
    dono - o mesmo esquema de permissoes do PDFCreator.
    """
    if not senha_dono:
        raise ValueError("a senha do dono e obrigatoria para proteger o PDF")
    permissoes = fitz.PDF_PERM_ACCESSIBILITY      # leitor de tela sempre liberado
    if imprimir:
        permissoes |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
    if copiar:
        permissoes |= fitz.PDF_PERM_COPY
    if alterar:
        permissoes |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ASSEMBLE
    if anotar:
        permissoes |= fitz.PDF_PERM_ANNOTATE
    if formularios:
        permissoes |= fitz.PDF_PERM_FORM
    return {
        "encryption": fitz.PDF_ENCRYPT_AES_256,
        "owner_pw": senha_dono,
        "user_pw": senha_abrir or "",
        "permissions": permissoes,
    }


# --------------------------------------------------------------------------
# Imagens <-> PDF
# --------------------------------------------------------------------------
EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")


TAMANHOS_PAGINA = {           # largura x altura em pontos, em pe
    "auto": None,             # a pagina segue o tamanho da imagem
    "a4": (595.0, 842.0),
    "carta": (612.0, 792.0),
    "oficio": (612.0, 1008.0),
}
ORIENTACOES = ("auto", "retrato", "paisagem")


def imagens_para_pdf(caminhos, tamanho="auto", orientacao="auto", margem=0.0):
    """Monta um PDF novo com uma pagina por imagem (TIFFs de varias paginas
    viram varias paginas).

    Com tamanho "auto" a pagina segue a resolucao da imagem. Com um tamanho
    de papel (A4, carta, oficio), a imagem e centralizada na folha sem
    distorcer, deixando `margem` pontos livres em volta; a orientacao "auto"
    deita a folha para imagens mais largas que altas, como no PDFCreator.
    """
    if tamanho not in TAMANHOS_PAGINA:
        raise ValueError("tamanho de pagina desconhecido: %r" % tamanho)
    if orientacao not in ORIENTACOES:
        raise ValueError("orientacao desconhecida: %r" % orientacao)
    doc = fitz.open()
    for caminho in caminhos:
        with fitz.open(caminho) as imagem:
            with fitz.open("pdf", imagem.convert_to_pdf()) as convertido:
                if TAMANHOS_PAGINA[tamanho] is None:
                    doc.insert_pdf(convertido)
                    continue
                for origem in convertido:
                    largura, altura = TAMANHOS_PAGINA[tamanho]
                    deitada = (orientacao == "paisagem" or
                               (orientacao == "auto" and origem.rect.width > origem.rect.height))
                    if deitada:
                        largura, altura = altura, largura
                    folha = doc.new_page(width=largura, height=altura)
                    area = fitz.Rect(margem, margem, largura - margem, altura - margem)
                    folha.show_pdf_page(area, convertido, origem.number, keep_proportion=True)
    return doc


FORMATOS_IMAGEM = ("png", "jpg", "tif")


def exportar_imagens(doc, pasta, nome_base, formato="png", dpi=150, paginas=None):
    """Grava as paginas como imagem e devolve a lista de arquivos criados.

    PNG e JPEG geram um arquivo por pagina (nome_base_001.png ...); TIFF gera
    um unico arquivo com todas as paginas, o formato usado por fax e por
    sistemas de arquivo digital.
    """
    if formato not in FORMATOS_IMAGEM:
        raise ValueError("formato desconhecido: %r" % formato)
    indices = list(range(doc.page_count)) if paginas is None else list(paginas)
    escala = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    criados = []
    if formato == "tif":
        from PIL import Image
        quadros = []
        for indice in indices:
            pix = doc[indice].get_pixmap(matrix=escala, alpha=False)
            quadros.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        if quadros:
            destino = os.path.join(pasta, nome_base + ".tif")
            quadros[0].save(destino, save_all=True, append_images=quadros[1:],
                            compression="tiff_deflate", dpi=(dpi, dpi))
            criados.append(destino)
        return criados
    digitos = max(3, len(str(len(indices))))
    for indice in indices:
        pix = doc[indice].get_pixmap(matrix=escala, alpha=False)
        pix.set_dpi(dpi, dpi)
        destino = os.path.join(pasta, "%s_%0*d.%s" % (nome_base, digitos, indice + 1, formato))
        if formato == "jpg":
            pix.save(destino, jpg_quality=90)
        else:
            pix.save(destino)
        criados.append(destino)
    return criados


# --------------------------------------------------------------------------
# Tamanho do arquivo e cores
# --------------------------------------------------------------------------
# Como as opcoes de compressao do PDFCreator: do "maxima" (arquivo menor,
# imagens mais leves) ao "minima" (quase sem perda), alem do "sem perda",
# que so recomprime o que da sem tocar na qualidade.
NIVEIS_COMPRESSAO = {         # (resolucao alvo em dpi, qualidade JPEG)
    "maxima": (72, 35),
    "alta": (110, 55),
    "media": (150, 70),
    "baixa": (200, 82),
    "minima": (300, 92),
    "sem_perda": None,
}


def otimizar_tamanho(doc, nivel="media"):
    """Reduz o peso das imagens do documento.

    Imagens com resolucao acima do alvo sao reamostradas para ele e
    regravadas em JPEG com a qualidade do nivel. Texto e desenhos vetoriais
    nao mudam. A limpeza de objetos repetidos e sem uso acontece ao salvar.
    Devolve (tamanho antes, tamanho depois) em bytes, ja com essa limpeza.
    """
    if nivel not in NIVEIS_COMPRESSAO:
        raise ValueError("nivel de compressao desconhecido: %r" % nivel)
    antes = len(doc.tobytes(garbage=4, deflate=True))
    if NIVEIS_COMPRESSAO[nivel]:
        dpi, qualidade = NIVEIS_COMPRESSAO[nivel]
        doc.rewrite_images(dpi_threshold=int(dpi * 1.1), dpi_target=dpi, quality=qualidade,
                           lossy=True, lossless=True, bitonal=False)
    try:
        doc.subset_fonts()
    except Exception:
        pass
    depois = len(doc.tobytes(garbage=4, deflate=True))
    return antes, depois


MODELOS_COR = {"cinza": 1, "cmyk": 4}


def converter_cores(doc, modelo="cinza"):
    """Converte texto, desenhos e imagens para tons de cinza (ou para CMYK,
    o modelo das graficas) - o "modelo de cor" do PDFCreator."""
    if modelo not in MODELOS_COR:
        raise ValueError("modelo de cor desconhecido: %r" % modelo)
    doc.recolor(MODELOS_COR[modelo])


# --------------------------------------------------------------------------
# Como o leitor abre o arquivo
# --------------------------------------------------------------------------
LAYOUTS = {                   # nome no editor -> /PageLayout do PDF
    "padrao": None,
    "uma_pagina": "SinglePage",
    "continua": "OneColumn",
    "duas_colunas_impar_esquerda": "TwoColumnLeft",
    "duas_colunas_impar_direita": "TwoColumnRight",
    "duas_paginas_impar_esquerda": "TwoPageLeft",
    "duas_paginas_impar_direita": "TwoPageRight",
}
PAINEIS = {                   # nome no editor -> /PageMode do PDF
    "padrao": None,
    "nenhum": "UseNone",
    "marcadores": "UseOutlines",
    "miniaturas": "UseThumbs",
    "tela_cheia": "FullScreen",
    "camadas": "UseOC",
    "anexos": "UseAttachments",
}


def definir_visualizacao(doc, layout="padrao", painel="padrao", pagina_inicial=1):
    """Diz ao leitor de PDF como abrir o documento: disposicao das paginas,
    painel lateral (marcadores, miniaturas...) ou tela cheia, e em que pagina
    comecar. "padrao" deixa a escolha para o leitor."""
    if layout not in LAYOUTS:
        raise ValueError("layout desconhecido: %r" % layout)
    if painel not in PAINEIS:
        raise ValueError("painel desconhecido: %r" % painel)
    catalogo = doc.pdf_catalog()
    if LAYOUTS[layout]:
        doc.set_pagelayout(LAYOUTS[layout])
    else:
        doc.xref_set_key(catalogo, "PageLayout", "null")
    if PAINEIS[painel]:
        doc.set_pagemode(PAINEIS[painel])
    else:
        doc.xref_set_key(catalogo, "PageMode", "null")
    indice = max(1, min(int(pagina_inicial), doc.page_count)) - 1
    if indice:
        doc.xref_set_key(catalogo, "OpenAction", "[%d 0 R /Fit]" % doc.page_xref(indice))
    else:
        doc.xref_set_key(catalogo, "OpenAction", "null")


# --------------------------------------------------------------------------
# Texto puro
# --------------------------------------------------------------------------
def exportar_texto(doc, destino):
    """Grava todo o texto do documento num arquivo .txt (UTF-8), na ordem de
    leitura, com uma quebra de pagina (form feed) entre as paginas - a saida
    "TXT" do PDFCreator. Devolve quantos caracteres foram gravados."""
    partes = [pagina.get_text("text", sort=True) for pagina in doc]
    texto = "\f".join(partes)
    with open(destino, "w", encoding="utf-8", newline="\n") as arquivo:
        arquivo.write(texto)
    return len(texto)
