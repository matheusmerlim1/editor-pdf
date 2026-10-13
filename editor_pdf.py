# -*- coding: utf-8 -*-
"""
Editor de PDF
=============
Abre um arquivo PDF, identifica o texto existente (com posicao, fonte, tamanho
e cor), permite editar esse texto e salvar novamente em PDF.

Como funciona a edicao:
  1. O texto do PDF e extraido em "trechos" (spans) - cada trecho e um pedaco
     de texto com formatacao homogenea, com sua caixa delimitadora na pagina.
  2. Ao aplicar uma alteracao, o trecho original e removido do PDF por meio de
     uma redacao (redaction) e o novo texto e escrito na mesma posicao,
     reaproveitando tamanho, cor e estilo (negrito/italico/serifada/mono).
  3. O documento e gravado novamente como PDF.

Requisitos: PyMuPDF, Pillow (tkinter ja acompanha o Python no Windows).
"""

import os
import re
import sys
import tempfile
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

try:
    import pymupdf as fitz
except ImportError:  # compatibilidade com versoes antigas do PyMuPDF
    import fitz

from PIL import Image, ImageTk

import acabamento as ac


APP_NOME = "Editor de PDF"
MAX_UNDO = 25
MARGEM_DIREITA = 5.0          # margem usada para caber o texto novo na pagina
LIMITE_ESPACO = 1.5           # espaco extra maximo entre palavras, em larguras de espaco
COR_CAIXA = "#c8c8ff"         # cor das caixas de texto detectadas
COR_SELECAO = "#ff0000"       # cor da caixa selecionada
COR_IMAGEM = "#f08c00"        # cor das caixas de imagem
PASSO_MOVER = 2.0             # pontos por clique nas setas de mover


# --------------------------------------------------------------------------
# Utilidades de fonte
# --------------------------------------------------------------------------
# Fontes base-14 do PDF (sempre disponiveis, nao precisam ser embutidas),
# organizadas por familia: (normal, negrito, italico, negrito+italico).
FAMILIAS_BASE14 = {
    "helv": ("helv", "hebo", "heit", "hebi"),   # Helvetica / sem serifa
    "tiro": ("tiro", "tibo", "tiit", "tibi"),   # Times / com serifa
    "cour": ("cour", "cobo", "coit", "cobi"),   # Courier / monoespacada
}


def caminho_recurso(relativo):
    """Localiza arquivos auxiliares tanto no codigo-fonte quanto no .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relativo)


def mapear_fonte(nome, flags):
    """Converte o nome/flags da fonte original em uma fonte base-14 equivalente."""
    n = (nome or "").lower()
    negrito = bool(flags & (1 << 4)) or any(k in n for k in ("bold", "black", "heavy", "semib"))
    italico = bool(flags & (1 << 1)) or any(k in n for k in ("italic", "oblique"))
    mono = bool(flags & (1 << 3)) or any(k in n for k in ("courier", "mono", "consol"))
    serifada = bool(flags & (1 << 2)) or any(
        k in n for k in ("times", "serif", "georgia", "roman", "garamond", "book", "cambria")
    )
    if mono:
        familia = "cour"
    elif serifada:
        familia = "tiro"
    else:
        familia = "helv"
    normal, bold, ital, bold_ital = FAMILIAS_BASE14[familia]
    if negrito and italico:
        return bold_ital
    if negrito:
        return bold
    if italico:
        return ital
    return normal


# As fontes base-14 cobrem apenas o conjunto latino-1. Estes caracteres
# tipograficos comuns sao convertidos para equivalentes que existem nelas.
SUBSTITUICOES = {
    u"—": "-", u"–": "-", u"−": "-",     # travessoes e sinal de menos
    u"‘": "'", u"’": "'", u"‚": ",",     # aspas simples curvas
    u"“": '"', u"”": '"', u"„": '"',     # aspas duplas curvas
    u"…": "...", u"•": "-", u" ": " ",   # reticencias, marcador, espaco fixo
    u" ": " ", u"​": "", u"ﬁ": "fi", u"ﬂ": "fl",
}


def normalizar_texto(texto):
    """Troca caracteres que as fontes base-14 nao possuem por equivalentes."""
    for origem, destino in SUBSTITUICOES.items():
        if origem in texto:
            texto = texto.replace(origem, destino)
    return texto


# Fontes embutidas ja extraidas do documento, para nao repetir o trabalho:
# {(id do documento, xref): objeto fitz.Font ou None}
_FONTES_EM_CACHE = {}


def normalizar_fonte(nome):
    """Reduz 'ABCDEF+Calibri-Bold' a 'calibribold', para poder comparar."""
    nome = (nome or "").split("+")[-1]
    return re.sub(r"[^a-z0-9]", "", nome.lower())


def fontes_da_pagina(pagina):
    """Fontes embutidas na pagina, pelo nome normalizado.

    Devolve, para cada uma, o nome de referencia dentro da pagina (que permite
    reaproveita-la sem duplicar o arquivo), o xref e o tipo.
    """
    mapa = {}
    try:
        for dados in pagina.get_fonts(full=True):
            xref, ext, tipo, basefont, refname = dados[0], dados[1], dados[2], dados[3], dados[4]
            if not refname or ext in ("n/a", ""):
                continue          # fonte nao embutida: nao da para reaproveitar
            mapa[normalizar_fonte(basefont)] = {
                "ref": refname, "xref": xref, "tipo": tipo, "nome": basefont,
                # Tw (espaco entre palavras) so vale para fontes de 1 byte
                "aceita_tw": tipo != "Type0",
            }
    except Exception:
        pass
    return mapa


def achar_fonte(mapa, nome_do_span):
    """Liga o nome da fonte que aparece no trecho a uma fonte da pagina."""
    alvo = normalizar_fonte(nome_do_span)
    if not alvo:
        return None
    if alvo in mapa:
        return mapa[alvo]
    for chave, info in mapa.items():          # 'Calibri' casa com 'CalibriRegular'
        if chave.startswith(alvo) or alvo.startswith(chave):
            return info
    return None


def fonte_embutida(documento, info):
    """Carrega a fonte do documento para medir texto e conferir os glifos."""
    if not info:
        return None
    chave = (id(documento), info["xref"])
    if chave not in _FONTES_EM_CACHE:
        try:
            buffer = documento.extract_font(info["xref"])[3]
            _FONTES_EM_CACHE[chave] = fitz.Font(fontbuffer=buffer) if buffer else None
        except Exception:
            _FONTES_EM_CACHE[chave] = None
    return _FONTES_EM_CACHE[chave]


def cor_para_rgb(valor):
    """Converte a cor inteira sRGB do PyMuPDF para tupla (r, g, b) de 0 a 1."""
    try:
        return tuple(fitz.sRGB_to_pdf(int(valor)))
    except Exception:
        return (0.0, 0.0, 0.0)


def cor_para_hex(rgb):
    r, g, b = [max(0, min(255, int(round(c * 255)))) for c in rgb]
    return "#%02x%02x%02x" % (r, g, b)


def hex_para_rgb(texto):
    texto = texto.lstrip("#")
    return tuple(int(texto[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


TIPOS_IMAGEM = [("Imagens", " ".join("*" + e for e in ac.EXTENSOES_IMAGEM))]


# --------------------------------------------------------------------------
# Imagens da pagina
# --------------------------------------------------------------------------
# Uma imagem e desenhada pelo operador "/Nome Do", e a posicao e o tamanho
# dela vem da matriz em vigor naquele ponto do fluxo de conteudo. Para mover,
# redimensionar ou apagar, o editor mexe so nessa chamada: acrescenta uma
# matriz extra antes dela (q ... cm /Nome Do Q) ou a retira. A imagem em si
# nao e recomprimida, sai de verdade do lugar antigo, e as outras paginas que
# usam o mesmo arquivo de imagem (um logotipo, por exemplo) nao mudam.
_DO = re.compile(rb"/([^\s/\[\]()<>{}%]+)\s+Do(?![A-Za-z0-9])")

# o quadrado unitario da imagem tem o eixo y para baixo no MuPDF e para cima no PDF
_VIRA_UNITARIO = fitz.Matrix(1, 0, 0, -1, 0, 1)


def _chamadas_de_imagem(pagina, nomes):
    """Cada '/Nome Do' de imagem nos fluxos da pagina: (xref do fluxo, inicio, fim, nome)."""
    documento = pagina.parent
    chamadas = []
    for xref in pagina.get_contents():
        fluxo = documento.xref_stream(xref) or b""
        for achado in _DO.finditer(fluxo):
            if achado.group(1).decode("latin-1") in nomes:
                chamadas.append((xref, achado.start(), achado.end(), achado.group(1)))
    return chamadas


def imagens_da_pagina(pagina):
    """Imagens desenhadas direto na pagina, na ordem em que sao pintadas.

    Cada uma traz a caixa ("bbox"), a matriz do MuPDF ("transform") e o tamanho
    em pixels. "movel" e falso quando o editor nao consegue ligar a imagem a
    uma chamada do fluxo (imagens dentro de formularios ou embutidas no fluxo).
    """
    try:
        nomes = {dados[7] for dados in pagina.get_images(full=True) if dados[9] == 0}
        infos = [i for i in pagina.get_image_info(xrefs=True) if i.get("xref", 0) > 0]
        chamadas = _chamadas_de_imagem(pagina, nomes)
    except Exception:
        return []
    movel = len(chamadas) == len(infos)
    return [{
        "bbox": tuple(info["bbox"]),
        "transform": tuple(info["transform"]),
        "xref": info["xref"],
        "px": (info.get("width", 0), info.get("height", 0)),
        "ordem": ordem,
        "movel": movel,
    } for ordem, info in enumerate(infos)]


def alterar_imagem(pagina, imagem, nova_caixa):
    """Leva a imagem para `nova_caixa` (Rect); com None, tira a imagem da pagina.

    Devolve a pagina recarregada: o objeto antigo guarda o conteudo de antes.
    """
    if not imagem.get("movel"):
        raise ValueError("esta imagem nao pode ser alterada (fica dentro de outro objeto)")
    nomes = {dados[7] for dados in pagina.get_images(full=True) if dados[9] == 0}
    chamadas = _chamadas_de_imagem(pagina, nomes)
    xref, inicio, fim, nome = chamadas[imagem["ordem"]]
    if nova_caixa is None:
        trecho = b""
    else:
        # C leva o quadrado unitario da imagem ao lugar atual, em coordenadas
        # do PDF; G leva a caixa atual a nova. Inserir C.G.C^-1 antes do Do
        # faz a matriz final virar C.G, ou seja, a imagem acaba na nova caixa.
        pdf_para_tela = pagina.transformation_matrix
        atual = fitz.Matrix(_VIRA_UNITARIO) * fitz.Matrix(imagem["transform"]) * ~pdf_para_tela
        velha, nova = fitz.Rect(imagem["bbox"]), fitz.Rect(nova_caixa)
        na_tela = (fitz.Matrix(1, 0, 0, 1, -velha.x0, -velha.y0) *
                   fitz.Matrix(nova.width / velha.width, 0, 0, nova.height / velha.height, 0, 0) *
                   fitz.Matrix(1, 0, 0, 1, nova.x0, nova.y0))
        ajuste = ~pdf_para_tela * na_tela * pdf_para_tela
        extra = atual * ajuste * ~atual
        trecho = (b"q %.6f %.6f %.6f %.6f %.4f %.4f cm /" % tuple(extra) + nome + b" Do Q")
    documento = pagina.parent
    fluxo = documento.xref_stream(xref)
    documento.update_stream(xref, fluxo[:inicio] + trecho + fluxo[fim:])
    return documento.reload_page(pagina)


# --------------------------------------------------------------------------
# Aplicacao
# --------------------------------------------------------------------------
class EditorPDF(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(APP_NOME)
        self.geometry("1250x800")
        self.minsize(1000, 620)
        try:
            self.iconbitmap(caminho_recurso(os.path.join("assets", "icone.ico")))
        except Exception:
            pass

        self.doc = None
        self.caminho = None
        self.pagina_atual = 0
        self.zoom = 1.4
        self.trechos = []          # trechos de texto da pagina exibida
        self.selecionado = None    # indice em self.trechos
        self.imagens = []          # imagens da pagina exibida
        self.img_sel = None        # indice em self.imagens
        self.arrasto = None        # objeto sendo arrastado na pagina
        self.pilha_undo = []
        self.modificado = False
        self.img_tk = None

        self._montar_interface()
        self._atualizar_titulo()
        self.protocol("WM_DELETE_WINDOW", self.ao_fechar)

        # Se o programa foi aberto arrastando um PDF (ou imagem) sobre o executavel.
        if len(sys.argv) > 1 and sys.argv[1].lower().endswith((".pdf",) + ac.EXTENSOES_IMAGEM):
            self.after(200, lambda: self.abrir(sys.argv[1]))

    # ---------------------------------------------------------------- UI --
    def _montar_interface(self):
        estilo = ttk.Style(self)
        try:
            estilo.theme_use("vista")
        except tk.TclError:
            pass

        # ---- menus
        menus = tk.Menu(self)
        arquivo = tk.Menu(menus, tearoff=False)
        arquivo.add_command(label="Abrir PDF...", accelerator="Ctrl+O", command=self.abrir)
        arquivo.add_command(label="Criar PDF a partir de imagens...", command=self.abrir_imagens)
        arquivo.add_separator()
        arquivo.add_command(label="Salvar", accelerator="Ctrl+S", command=self.salvar)
        arquivo.add_command(label="Salvar como...", command=self.salvar_como)
        arquivo.add_command(label="Salvar copia protegida com senha...",
                            command=self.salvar_protegido)
        arquivo.add_command(label="Exportar paginas como imagem...",
                            command=self.exportar_imagens)
        arquivo.add_separator()
        arquivo.add_command(label="Sair", command=self.ao_fechar)
        menus.add_cascade(label="Arquivo", menu=arquivo)

        editar = tk.Menu(menus, tearoff=False)
        editar.add_command(label="Desfazer", accelerator="Ctrl+Z", command=self.desfazer)
        editar.add_command(label="Localizar e substituir...", accelerator="Ctrl+H",
                           command=self.localizar_substituir)
        menus.add_cascade(label="Editar", menu=editar)

        documento = tk.Menu(menus, tearoff=False)
        documento.add_command(label="Numerar paginas...", command=self.numerar_paginas)
        documento.add_command(label="Carimbo / marca d'agua...", command=self.carimbar)
        documento.add_command(label="Papel timbrado (fundo)...", command=self.papel_timbrado)
        documento.add_separator()
        documento.add_command(label="Inserir capa...", command=self.inserir_capa)
        documento.add_command(label="Anexar arquivos ao final...", command=self.anexar_arquivos)
        documento.add_separator()
        documento.add_command(label="Propriedades (titulo, autor...)...",
                              command=self.propriedades)
        menus.add_cascade(label="Documento", menu=documento)
        self.config(menu=menus)

        # ---- barra de ferramentas
        barra = ttk.Frame(self, padding=(8, 6))
        barra.pack(side="top", fill="x")

        ttk.Button(barra, text="Abrir PDF", command=self.abrir).pack(side="left")
        ttk.Button(barra, text="Salvar", command=self.salvar).pack(side="left", padx=(6, 0))
        ttk.Button(barra, text="Salvar como...", command=self.salvar_como).pack(side="left", padx=(6, 0))
        ttk.Separator(barra, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Button(barra, text="Desfazer", command=self.desfazer).pack(side="left")
        ttk.Button(barra, text="Localizar e substituir",
                   command=self.localizar_substituir).pack(side="left", padx=(6, 0))
        ttk.Separator(barra, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Button(barra, text="<", width=3, command=self.pagina_anterior).pack(side="left")
        self.var_pagina = tk.StringVar(value="0")
        ent = ttk.Entry(barra, textvariable=self.var_pagina, width=5, justify="center")
        ent.pack(side="left", padx=4)
        ent.bind("<Return>", self.ir_para_pagina)
        self.lbl_total = ttk.Label(barra, text="/ 0")
        self.lbl_total.pack(side="left")
        ttk.Button(barra, text=">", width=3, command=self.proxima_pagina).pack(side="left", padx=(4, 0))
        ttk.Separator(barra, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Button(barra, text="Zoom -", command=lambda: self.alterar_zoom(-0.2)).pack(side="left")
        ttk.Button(barra, text="Zoom +", command=lambda: self.alterar_zoom(0.2)).pack(side="left", padx=(6, 0))
        self.var_caixas = tk.BooleanVar(value=True)
        ttk.Checkbutton(barra, text="Mostrar caixas de texto", variable=self.var_caixas,
                        command=self.desenhar_caixas).pack(side="left", padx=(12, 0))

        # ---- corpo dividido: pagina | painel de edicao
        painel = ttk.PanedWindow(self, orient="horizontal")
        painel.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        quadro_pg = ttk.Frame(painel)
        self.canvas = tk.Canvas(quadro_pg, bg="#5a5a5a", highlightthickness=0)
        vsb = ttk.Scrollbar(quadro_pg, orient="vertical", command=self.canvas.yview)
        hsb = ttk.Scrollbar(quadro_pg, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        quadro_pg.rowconfigure(0, weight=1)
        quadro_pg.columnconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self.clique_no_canvas)
        self.canvas.bind("<B1-Motion>", self.arrastar)
        self.canvas.bind("<ButtonRelease-1>", self.soltar)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(-1 * (e.delta // 120), "units"))
        painel.add(quadro_pg, weight=3)

        lateral = ttk.Frame(painel)
        painel.add(lateral, weight=1)

        ttk.Label(lateral, text="Textos encontrados na pagina (imagens: contorno laranja)",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        quadro_lista = ttk.Frame(lateral)
        quadro_lista.pack(fill="both", expand=True)
        self.lista = tk.Listbox(quadro_lista, activestyle="dotbox", exportselection=False)
        sbl = ttk.Scrollbar(quadro_lista, orient="vertical", command=self.lista.yview)
        self.lista.configure(yscrollcommand=sbl.set)
        self.lista.pack(side="left", fill="both", expand=True)
        sbl.pack(side="right", fill="y")
        self.lista.bind("<<ListboxSelect>>", self.selecionar_da_lista)

        ttk.Separator(lateral, orient="horizontal").pack(fill="x", pady=8)

        self.lbl_info = ttk.Label(lateral, text="Nenhum trecho selecionado.",
                                  wraplength=320, foreground="#444")
        self.lbl_info.pack(anchor="w")

        ttk.Label(lateral, text="Texto (edite abaixo):",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(8, 2))
        self.txt_edicao = tk.Text(lateral, height=6, wrap="word", font=("Consolas", 10))
        self.txt_edicao.pack(fill="x")

        botoes = ttk.Frame(lateral)
        botoes.pack(fill="x", pady=6)
        ttk.Button(botoes, text="Aplicar alteracao", command=self.aplicar_edicao).pack(side="left")
        ttk.Button(botoes, text="Restaurar", command=self.restaurar_edicao).pack(side="left", padx=6)
        ttk.Button(botoes, text="Apagar", command=self.apagar_selecao).pack(side="left")

        # mover o texto ou a imagem selecionada (tambem da para arrastar)
        mover = ttk.Frame(lateral)
        mover.pack(fill="x", pady=(2, 0))
        ttk.Label(mover, text="Mover:").pack(side="left", padx=(0, 4))
        for rotulo, dx, dy in (("<", -1, 0), ("^", 0, -1), ("v", 0, 1), (">", 1, 0)):
            ttk.Button(mover, text=rotulo, width=3,
                       command=lambda dx=dx, dy=dy: self.mover_selecao(
                           dx * PASSO_MOVER, dy * PASSO_MOVER)).pack(side="left", padx=1)
        ttk.Label(mover, text="ou arraste na pagina", foreground="#666").pack(side="left", padx=6)

        tamanho = ttk.Frame(lateral)
        tamanho.pack(fill="x", pady=(6, 0))
        ttk.Label(tamanho, text="Tamanho da imagem (%):").pack(side="left")
        self.var_escala = tk.StringVar(value="100")
        ent_escala = ttk.Entry(tamanho, textvariable=self.var_escala, width=6, justify="center")
        ent_escala.pack(side="left", padx=4)
        ent_escala.bind("<Return>", lambda e: self.redimensionar_imagem())
        ttk.Button(tamanho, text="Aplicar", command=self.redimensionar_imagem).pack(side="left")

        # ---- barra de status
        self.var_status = tk.StringVar(value="Abra um arquivo PDF para comecar.")
        ttk.Label(self, textvariable=self.var_status, relief="sunken",
                  anchor="w", padding=(6, 3)).pack(side="bottom", fill="x")

        # atalhos de teclado
        self.bind("<Control-o>", lambda e: self.abrir())
        self.bind("<Control-s>", lambda e: self.salvar())
        self.bind("<Control-z>", lambda e: self.desfazer())
        self.bind("<Control-h>", lambda e: self.localizar_substituir())
        for tecla, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self.bind("<Alt-%s>" % tecla, lambda e, dx=dx, dy=dy: self.mover_selecao(
                dx * PASSO_MOVER, dy * PASSO_MOVER))
        self.bind("<Prior>", lambda e: self.pagina_anterior())
        self.bind("<Next>", lambda e: self.proxima_pagina())

    def status(self, texto):
        self.var_status.set(texto)
        self.update_idletasks()

    def _atualizar_titulo(self):
        if self.doc is not None:
            self.title("%s - %s%s" % (APP_NOME,
                                      os.path.basename(self.caminho or "sem nome"),
                                      " *" if self.modificado else ""))
            self.lbl_total.config(text="/ %d" % self.doc.page_count)
        else:
            self.title(APP_NOME)
            self.lbl_total.config(text="/ 0")

    # ------------------------------------------------------------ arquivo --
    def abrir(self, caminho=None):
        if not self.confirmar_descartar():
            return
        if caminho is None:
            caminho = filedialog.askopenfilename(
                title="Abrir PDF",
                filetypes=[("Arquivos PDF", "*.pdf")] + TIPOS_IMAGEM +
                          [("Todos os arquivos", "*.*")])
        if not caminho:
            return
        if caminho.lower().endswith(ac.EXTENSOES_IMAGEM):
            self._abrir_imagens([caminho])
            return
        doc = self._abrir_pdf(caminho)
        if doc is None:
            return
        self._trocar_documento(doc, caminho, modificado=False)
        if sum(len(p.get_text().strip()) for p in self.doc) == 0:
            messagebox.showwarning(
                APP_NOME,
                "Este PDF nao possui texto pesquisavel (provavelmente e um documento\n"
                "digitalizado, formado apenas por imagens).\n\n"
                "Para edita-lo seria necessario reconhecimento optico de caracteres (OCR).")
        self.status("Aberto: %s (%d paginas)" % (caminho, self.doc.page_count))

    def _abrir_pdf(self, caminho):
        """Abre um PDF pedindo a senha, se precisar. Devolve None se nao der."""
        try:
            doc = fitz.open(caminho)
        except Exception as exc:
            messagebox.showerror(APP_NOME, "Nao foi possivel abrir o arquivo:\n\n%s" % exc)
            return None
        if doc.needs_pass:
            senha = SenhaDialog(self).resultado
            if not senha or not doc.authenticate(senha):
                messagebox.showerror(APP_NOME, "PDF protegido: senha invalida ou nao informada.")
                doc.close()
                return None
        return doc

    def _abrir_como_pdf(self, caminho):
        """PDF ou imagem, sempre devolvido como documento PDF (ou None)."""
        if caminho.lower().endswith(ac.EXTENSOES_IMAGEM):
            try:
                return ac.imagens_para_pdf([caminho])
            except Exception as exc:
                messagebox.showerror(APP_NOME, "Nao foi possivel ler a imagem:\n\n%s" % exc)
                return None
        return self._abrir_pdf(caminho)

    def _trocar_documento(self, doc, caminho, modificado):
        if self.doc is not None:
            self.doc.close()
        self.doc = doc
        self.caminho = caminho
        self.pagina_atual = 0
        self.pilha_undo.clear()
        self.modificado = modificado
        self.carregar_pagina()
        self._atualizar_titulo()

    def abrir_imagens(self):
        if not self.confirmar_descartar():
            return
        caminhos = filedialog.askopenfilenames(
            title="Escolha as imagens (uma pagina por imagem, na ordem escolhida)",
            filetypes=TIPOS_IMAGEM + [("Todos os arquivos", "*.*")])
        if caminhos:
            self._abrir_imagens(list(caminhos))

    def _abrir_imagens(self, caminhos):
        try:
            doc = ac.imagens_para_pdf(caminhos)
        except Exception as exc:
            messagebox.showerror(APP_NOME, "Nao foi possivel converter as imagens:\n\n%s" % exc)
            return
        # documento novo, ainda sem arquivo: "Salvar" vai pedir o nome
        self._trocar_documento(doc, None, modificado=True)
        self.status("PDF criado a partir de %d imagem(ns). Use 'Salvar como...' para gravar."
                    % len(caminhos))

    def salvar(self):
        if self.doc is None:
            return
        if not self.caminho:
            self.salvar_como()
            return
        self._gravar(self.caminho)

    def salvar_como(self):
        if self.doc is None:
            messagebox.showinfo(APP_NOME, "Abra um PDF antes de salvar.")
            return
        raiz, _ = os.path.splitext(os.path.basename(self.caminho or "documento.pdf"))
        destino = filedialog.asksaveasfilename(
            title="Salvar PDF como", defaultextension=".pdf",
            initialfile=raiz + "_editado.pdf",
            filetypes=[("Arquivos PDF", "*.pdf")])
        if destino:
            self._gravar(destino)

    def _gravar(self, destino):
        try:
            try:
                self.doc.subset_fonts()   # deixa so os glifos usados
            except Exception:
                pass
            mesmo = self.caminho and os.path.abspath(destino) == os.path.abspath(self.caminho)
            if mesmo:
                # Nao e possivel gravar por cima do arquivo aberto: usa temporario.
                fd, temporario = tempfile.mkstemp(suffix=".pdf",
                                                  dir=os.path.dirname(destino) or ".")
                os.close(fd)
                self.doc.save(temporario, garbage=4, deflate=True)
                self.doc.close()
                os.replace(temporario, destino)
                self.doc = fitz.open(destino)
            else:
                self.doc.save(destino, garbage=4, deflate=True)
                self.caminho = destino
            self.modificado = False
            self.pilha_undo.clear()
            self.carregar_pagina()
            self._atualizar_titulo()
            self.status("Salvo em: %s" % destino)
            messagebox.showinfo(APP_NOME, "PDF salvo com sucesso em:\n\n%s" % destino)
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror(APP_NOME, "Erro ao salvar:\n\n%s" % exc)

    def confirmar_descartar(self):
        if self.doc is None or not self.modificado:
            return True
        r = messagebox.askyesnocancel(APP_NOME, "Existem alteracoes nao salvas. Deseja salvar agora?")
        if r is None:
            return False
        if r:
            self.salvar()
            return not self.modificado
        return True

    def ao_fechar(self):
        if self.confirmar_descartar():
            if self.doc is not None:
                self.doc.close()
            self.destroy()

    # ------------------------------------------------------------- paginas --
    def carregar_pagina(self):
        if self.doc is None:
            return
        self.pagina_atual = max(0, min(self.pagina_atual, self.doc.page_count - 1))
        pagina = self.doc[self.pagina_atual]
        self.trechos = self.extrair_trechos(pagina)
        self.selecionado = None
        self.imagens = imagens_da_pagina(pagina)
        self.img_sel = None
        self.var_pagina.set(str(self.pagina_atual + 1))
        self.renderizar(pagina)
        self.preencher_lista()
        self.txt_edicao.delete("1.0", "end")
        self.lbl_info.config(text="Nenhum trecho selecionado.")

    def renderizar(self, pagina=None):
        if self.doc is None:
            return
        if pagina is None:
            pagina = self.doc[self.pagina_atual]
        pix = pagina.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self.img_tk = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.img_tk, tags="pagina")
        self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))
        self.desenhar_caixas()

    def desenhar_caixas(self):
        self.canvas.delete("caixa")
        if self.doc is None:
            return
        if self.var_caixas.get():
            for img in self.imagens:
                x0, y0, x1, y1 = [v * self.zoom for v in img["bbox"]]
                self.canvas.create_rectangle(x0, y0, x1, y1, outline=COR_IMAGEM,
                                             dash=(4, 3), tags="caixa")
            for t in self.trechos:
                x0, y0, x1, y1 = [v * self.zoom for v in t["bbox"]]
                self.canvas.create_rectangle(x0, y0, x1, y1, outline=COR_CAIXA, tags="caixa")
        if self.img_sel is not None and 0 <= self.img_sel < len(self.imagens):
            x0, y0, x1, y1 = [v * self.zoom for v in self.imagens[self.img_sel]["bbox"]]
            self.canvas.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1,
                                         outline=COR_IMAGEM, width=2, tags="caixa")
        if self.selecionado is not None and 0 <= self.selecionado < len(self.trechos):
            x0, y0, x1, y1 = [v * self.zoom for v in self.trechos[self.selecionado]["bbox"]]
            self.canvas.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1,
                                         outline=COR_SELECAO, width=2, tags="caixa")

    def pagina_anterior(self):
        if self.doc and self.pagina_atual > 0:
            self.pagina_atual -= 1
            self.carregar_pagina()

    def proxima_pagina(self):
        if self.doc and self.pagina_atual < self.doc.page_count - 1:
            self.pagina_atual += 1
            self.carregar_pagina()

    def ir_para_pagina(self, evento=None):
        if self.doc is None:
            return
        try:
            self.pagina_atual = int(self.var_pagina.get()) - 1
        except ValueError:
            self.var_pagina.set(str(self.pagina_atual + 1))
            return
        self.carregar_pagina()

    def alterar_zoom(self, delta):
        self.zoom = max(0.4, min(4.0, self.zoom + delta))
        self.renderizar()
        self.status("Zoom: %d%%" % int(self.zoom * 100))

    # ------------------------------------------------------ extracao texto --
    def extrair_trechos(self, pagina):
        """Le a pagina e devolve a lista de trechos de texto com sua formatacao."""
        trechos = []
        try:
            dados = pagina.get_text("dict")
        except Exception:
            return trechos
        embutidas = fontes_da_pagina(pagina)
        for bloco in dados.get("blocks", []):
            if bloco.get("type", 1) != 0:      # 0 = bloco de texto
                continue
            for linha in bloco.get("lines", []):
                for span in linha.get("spans", []):
                    texto = span.get("text", "")
                    if not texto.strip():
                        continue
                    flags = int(span.get("flags", 0))
                    bbox = tuple(span["bbox"])
                    trechos.append({
                        "text": texto,
                        "bbox": bbox,
                        "origin": tuple(span.get("origin", (bbox[0], bbox[3]))),
                        "size": float(span.get("size", 11)),
                        "font": span.get("font", ""),
                        "flags": flags,
                        "rgb": cor_para_rgb(span.get("color", 0)),
                        "base14": mapear_fonte(span.get("font", ""), flags),
                        # fonte do proprio documento, quando embutida
                        "fonte_doc": achar_fonte(embutidas, span.get("font", "")),
                    })
        return trechos

    def preencher_lista(self):
        self.lista.delete(0, "end")
        for i, t in enumerate(self.trechos):
            resumo = t["text"].strip()
            if len(resumo) > 60:
                resumo = resumo[:57] + "..."
            self.lista.insert("end", "%3d  %s" % (i + 1, resumo))
        self.status("Pagina %d de %d - %d trechos de texto encontrados."
                    % (self.pagina_atual + 1, self.doc.page_count, len(self.trechos)))

    # -------------------------------------------------------------- selecao --
    def clique_no_canvas(self, evento):
        if self.doc is None:
            return
        x = self.canvas.canvasx(evento.x) / self.zoom
        y = self.canvas.canvasy(evento.y) / self.zoom
        self.arrasto = None
        # o texto tem prioridade sobre a imagem que estiver embaixo dele
        alvo = self._no_ponto(self.trechos, x, y)
        if alvo is not None:
            if alvo != self.selecionado:
                self.selecionar(alvo)
            caixa = self.trechos[alvo]["bbox"]
        else:
            alvo = self._no_ponto(self.imagens, x, y)
            if alvo is None:
                self.status("Nenhum texto ou imagem nesse ponto.")
                return
            if alvo != self.img_sel:
                self.selecionar_imagem(alvo)
            caixa = self.imagens[alvo]["bbox"]
        self.arrasto = {"inicio": (x, y), "caixa": caixa, "delta": (0.0, 0.0)}

    @staticmethod
    def _no_ponto(objetos, x, y):
        """Indice do menor objeto (por area) cuja caixa contem o ponto."""
        alvo, menor = None, None
        for i, objeto in enumerate(objetos):
            x0, y0, x1, y1 = objeto["bbox"]
            if x0 <= x <= x1 and y0 <= y <= y1:
                area = (x1 - x0) * (y1 - y0)
                if menor is None or area < menor:
                    menor, alvo = area, i
        return alvo

    def arrastar(self, evento):
        """Mostra, tracejado, onde o objeto vai ficar enquanto e arrastado."""
        if not self.arrasto:
            return
        x = self.canvas.canvasx(evento.x) / self.zoom
        y = self.canvas.canvasy(evento.y) / self.zoom
        dx, dy = x - self.arrasto["inicio"][0], y - self.arrasto["inicio"][1]
        self.arrasto["delta"] = (dx, dy)
        x0, y0, x1, y1 = self.arrasto["caixa"]
        self.canvas.delete("arrasto")
        self.canvas.create_rectangle((x0 + dx) * self.zoom, (y0 + dy) * self.zoom,
                                     (x1 + dx) * self.zoom, (y1 + dy) * self.zoom,
                                     outline=COR_SELECAO, dash=(5, 3), width=2, tags="arrasto")

    def soltar(self, evento):
        if not self.arrasto:
            return
        dx, dy = self.arrasto["delta"]
        self.arrasto = None
        self.canvas.delete("arrasto")
        if abs(dx) * self.zoom > 3 or abs(dy) * self.zoom > 3:   # foi arrasto, nao clique
            self.mover_selecao(dx, dy)

    def selecionar_da_lista(self, evento=None):
        sel = self.lista.curselection()
        if sel:
            self.selecionar(sel[0], rolar_lista=False)

    def selecionar(self, indice, rolar_lista=True):
        self.selecionado = indice
        self.img_sel = None
        t = self.trechos[indice]
        if rolar_lista:
            self.lista.selection_clear(0, "end")
            self.lista.selection_set(indice)
            self.lista.see(indice)
        self.txt_edicao.delete("1.0", "end")
        self.txt_edicao.insert("1.0", t["text"])
        self.lbl_info.config(
            text="Fonte original: %s | tamanho: %.1f | cor: %s\nFonte usada na regravacao: %s"
                 % (t["font"] or "?", t["size"], cor_para_hex(t["rgb"]), t["base14"]))
        self.desenhar_caixas()

    def selecionar_imagem(self, indice):
        self.img_sel = indice
        self.selecionado = None
        img = self.imagens[indice]
        x0, y0, x1, y1 = img["bbox"]
        self.lista.selection_clear(0, "end")
        self.txt_edicao.delete("1.0", "end")
        self.var_escala.set("100")
        aviso = "" if img["movel"] else "\nEsta imagem fica dentro de outro objeto e nao pode ser alterada."
        self.lbl_info.config(
            text="Imagem %d: %d x %d pixels, ocupando %.0f x %.0f pt na posicao %.0f, %.0f.%s"
                 % (indice + 1, img["px"][0], img["px"][1], x1 - x0, y1 - y0, x0, y0, aviso))
        self.status("Imagem selecionada: arraste para mover, use as setas ou mude o tamanho.")
        self.desenhar_caixas()

    def restaurar_edicao(self):
        if self.selecionado is not None:
            self.txt_edicao.delete("1.0", "end")
            self.txt_edicao.insert("1.0", self.trechos[self.selecionado]["text"])

    # -------------------------------------------------------------- edicao --
    def guardar_undo(self):
        try:
            self.pilha_undo.append(self.doc.tobytes())
            if len(self.pilha_undo) > MAX_UNDO:
                self.pilha_undo.pop(0)
        except Exception:
            pass

    def desfazer(self):
        if not self.pilha_undo:
            self.status("Nada para desfazer.")
            return
        dados = self.pilha_undo.pop()
        self.doc.close()
        self.doc = fitz.open("pdf", dados)
        self.modificado = True
        self.carregar_pagina()
        self._atualizar_titulo()
        self.status("Alteracao desfeita.")

    def aplicar_edicao(self, deslocamento=(0.0, 0.0)):
        if self.doc is None or self.selecionado is None:
            messagebox.showinfo(APP_NOME, "Selecione um trecho de texto na pagina ou na lista.")
            return
        novo = self.txt_edicao.get("1.0", "end-1c").replace("\r", " ").replace("\n", " ")
        trecho = self.trechos[self.selecionado]
        if novo == trecho["text"] and deslocamento == (0.0, 0.0):
            self.status("O texto nao foi alterado.")
            return
        if not novo.strip():
            self.status("O texto esta vazio. Para tirar o trecho, use 'Apagar'.")
            return
        self.guardar_undo()
        try:
            transbordou = self.substituir_trechos(self.doc[self.pagina_atual],
                                                  [(trecho, novo, deslocamento)])
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror(APP_NOME, "Nao foi possivel aplicar a alteracao:\n\n%s" % exc)
            return
        self.modificado = True
        destino = (trecho["origin"][0] + deslocamento[0], trecho["origin"][1] + deslocamento[1])
        self.carregar_pagina()
        self._atualizar_titulo()
        if self.trechos:
            # o trecho pode mudar de posicao na lista: e procurado pelo lugar
            perto = min(range(len(self.trechos)), key=lambda i: (
                (self.trechos[i]["origin"][0] - destino[0]) ** 2 +
                (self.trechos[i]["origin"][1] - destino[1]) ** 2))
            self.selecionar(perto)
        if deslocamento != (0.0, 0.0) and novo == trecho["text"]:
            self.status("Texto movido %.1f pt na horizontal e %.1f pt na vertical. Ctrl+Z desfaz."
                        % deslocamento)
        elif transbordou:
            self.status("Texto alterado (o corpo %.1f foi mantido, mas o texto passou da "
                        "margem da pagina)." % trecho["size"])
        else:
            self.status("Texto alterado. Use 'Salvar' ou 'Salvar como...' para gravar o PDF.")

    def mover_selecao(self, dx, dy):
        """Desloca o texto ou a imagem selecionada, em pontos."""
        if self.doc is None:
            return
        if self.img_sel is not None:
            x0, y0, x1, y1 = self.imagens[self.img_sel]["bbox"]
            self._alterar_imagem(fitz.Rect(x0 + dx, y0 + dy, x1 + dx, y1 + dy), "Imagem movida.")
        elif self.selecionado is not None:
            self.aplicar_edicao(deslocamento=(dx, dy))
        else:
            self.status("Selecione um texto ou uma imagem para mover.")

    def redimensionar_imagem(self):
        if self.img_sel is None:
            messagebox.showinfo(APP_NOME, "Selecione uma imagem na pagina.")
            return
        try:
            fator = float(self.var_escala.get().replace(",", ".").rstrip("%")) / 100.0
        except ValueError:
            messagebox.showerror(APP_NOME, "O tamanho precisa ser um numero (100 = como esta).")
            return
        if not 0.05 <= fator <= 20:
            messagebox.showerror(APP_NOME, "Use um tamanho entre 5% e 2000%.")
            return
        if fator == 1:
            return
        x0, y0, x1, y1 = self.imagens[self.img_sel]["bbox"]
        # o canto de cima a esquerda fica no lugar e a proporcao e mantida
        self._alterar_imagem(fitz.Rect(x0, y0, x0 + (x1 - x0) * fator, y0 + (y1 - y0) * fator),
                             "Imagem redimensionada para %g%%." % (fator * 100))

    def _alterar_imagem(self, nova_caixa, mensagem):
        imagem = self.imagens[self.img_sel]
        if not imagem["movel"]:
            messagebox.showinfo(APP_NOME, "Esta imagem fica dentro de outro objeto do PDF e "
                                          "nao pode ser alterada pelo editor.")
            return
        self.guardar_undo()
        try:
            alterar_imagem(self.doc[self.pagina_atual], imagem, nova_caixa)
        except Exception as exc:
            traceback.print_exc()
            if self.pilha_undo:
                self.pilha_undo.pop()
            messagebox.showerror(APP_NOME, "Nao foi possivel alterar a imagem:\n\n%s" % exc)
            return
        self.modificado = True
        self.carregar_pagina()
        self._atualizar_titulo()
        if nova_caixa is not None and imagem["ordem"] < len(self.imagens):
            self.selecionar_imagem(imagem["ordem"])
        self.status(mensagem + " Ctrl+Z desfaz.")

    def apagar_selecao(self):
        if self.img_sel is not None:
            if messagebox.askyesno(APP_NOME, "Remover esta imagem da pagina?"):
                self._alterar_imagem(None, "Imagem removida.")
        else:
            self.apagar_trecho()

    def apagar_trecho(self):
        if self.doc is None or self.selecionado is None:
            return
        if not messagebox.askyesno(APP_NOME, "Remover este trecho de texto do PDF?"):
            return
        self.guardar_undo()
        self.substituir_trechos(self.doc[self.pagina_atual],
                                [(self.trechos[self.selecionado], "")])
        self.modificado = True
        self.carregar_pagina()
        self._atualizar_titulo()
        self.status("Trecho removido.")

    # ---- nucleo: troca do texto dentro do PDF -----------------------------
    def substituir_trechos(self, pagina, pares):
        """Remove os trechos originais e escreve os novos textos na mesma posicao.

        `pares` e uma lista de tuplas (trecho, texto_novo) ou
        (trecho, texto_novo, (dx, dy)) - o terceiro item desloca o texto novo
        em pontos, a partir do lugar original. Passar texto vazio apenas apaga
        o trecho.
        """
        if not pares:
            return
        pares = [tuple(par) + ((0.0, 0.0),) * (3 - len(par)) for par in pares]
        rotacao = pagina.rotation
        desrotacao = pagina.derotation_matrix

        # 1) marca as areas a serem apagadas
        for trecho, _, _ in pares:
            ret = fitz.Rect(trecho["bbox"]) * desrotacao
            pagina.add_redact_annot(ret.normalize(), fill=None, cross_out=False)

        # 2) apaga somente o texto, preservando imagens e desenhos
        if rotacao:
            pagina.set_rotation(0)
        pagina.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                text=fitz.PDF_REDACT_TEXT_REMOVE)

        # 3) escreve o texto novo
        limite = pagina.rect.x1 - MARGEM_DIREITA
        giro = (360 - rotacao) % 360
        transbordaram = 0
        for trecho, novo, (dx, dy) in pares:
            if not novo.strip():
                continue
            novo = normalizar_texto(novo)
            ponto = fitz.Point(trecho["origin"][0] + dx, trecho["origin"][1] + dy) * desrotacao
            tamanho = trecho["size"]     # o corpo original e sempre mantido

            # A fonte do proprio documento e preferida: reaproveitada pelo nome
            # que ja consta nos recursos da pagina, ela nao duplica o arquivo e
            # mantem o desenho exato das letras. So e trocada pela base-14
            # equivalente quando nao esta embutida ou nao tem algum caractere.
            info = trecho.get("fonte_doc")
            fonte_doc = fonte_embutida(pagina.parent, info)
            fonte = trecho["base14"]
            medir = lambda t, c=tamanho: fitz.get_text_length(t, fontname=trecho["base14"], fontsize=c)
            aceita_tw = True
            if fonte_doc is not None and all(fonte_doc.has_glyph(ord(c)) for c in novo):
                nome_na_pagina = self.garantir_fonte(pagina, info)
                if nome_na_pagina:
                    fonte = nome_na_pagina
                    aceita_tw = info["aceita_tw"]
                    medir = lambda t, c=tamanho: fonte_doc.text_length(t, fontsize=c)

            if medir(novo) > limite - ponto.x:
                transbordaram += 1

            # Linhas justificadas trazem espaco extra entre as palavras. Sem ele
            # a linha encolheria e deixaria de alcancar a margem; a folga que o
            # trecho original tinha e devolvida aqui. O sinal de que a linha era
            # justificada e o proprio texto original ocupar menos do que a caixa
            # dele - numa linha comum os dois valores batem, e ai nada e
            # espalhado, mesmo que o texto novo seja mais curto.
            largura_alvo = trecho["bbox"][2] - trecho["bbox"][0]
            era_espalhada = medir(trecho["text"]) < largura_alvo - 0.5
            extra = self.espaco_extra(novo, medir, largura_alvo) if era_espalhada else 0.0

            if extra and not aceita_tw:
                # fontes de 2 bytes ignoram o operador Tw: as palavras vao uma
                # a uma, em posicoes calculadas
                x = ponto.x
                for palavra in novo.split(" "):
                    if palavra:
                        self.escrever(pagina, fitz.Point(x, ponto.y), palavra,
                                      fonte, tamanho, trecho["rgb"], giro)
                    x += medir(palavra + " ") + extra
            else:
                antes = set(pagina.get_contents())
                self.escrever(pagina, ponto, novo, fonte, tamanho, trecho["rgb"], giro)
                if extra:
                    self.ajustar_espacamento(pagina, antes, extra)
        if rotacao:
            pagina.set_rotation(rotacao)
        return transbordaram

    @staticmethod
    def garantir_fonte(pagina, info):
        """Deixa a fonte do documento disponivel na pagina e devolve o nome dela.

        Primeiro tenta reaproveitar o recurso que ja esta na pagina, o que nao
        duplica nada no arquivo. A redacao remove esse recurso quando nenhum
        outro texto da pagina usava a fonte; nesse caso ela e reinserida a
        partir do proprio documento, e a copia sem uso sai na limpeza da
        gravacao. Devolve None quando nao da para usar a fonte original.
        """
        try:
            pagina.insert_font(fontname=info["ref"])
            return info["ref"]
        except Exception:
            pass
        try:
            buffer = pagina.parent.extract_font(info["xref"])[3]
            if not buffer:
                return None
            nome = "doc%d" % info["xref"]
            pagina.insert_font(fontname=nome, fontbuffer=buffer)
            return nome
        except Exception:
            return None

    @staticmethod
    def escrever(pagina, ponto, texto, fonte, tamanho, cor, giro):
        """Escreve o texto, caindo na fonte padrao se algum caractere faltar."""
        try:
            pagina.insert_text(ponto, texto, fontname=fonte, fontsize=tamanho,
                               color=cor, rotate=giro)
        except Exception:
            seguro = texto.encode("latin-1", "replace").decode("latin-1")
            pagina.insert_text(ponto, seguro, fontname="helv", fontsize=tamanho,
                               color=cor, rotate=giro)

    @staticmethod
    def ajustar_espacamento(pagina, xrefs_antes, extra):
        """Acrescenta o operador Tw (espaco entre palavras) ao texto recem-escrito.

        O PDF usa Tw para justificar linhas; aplicando o mesmo valor, o texto
        novo ocupa a largura que o trecho original tinha, e continua sendo um
        unico trecho de texto para futuras edicoes.
        """
        try:
            documento = pagina.parent
            conteudos = pagina.get_contents()
            novos = [x for x in conteudos if x not in xrefs_antes]
            xref = novos[-1] if novos else (conteudos[-1] if conteudos else 0)
            if not xref:
                return
            fluxo = documento.xref_stream(xref)
            marcas = list(re.finditer(rb"/[^\s/]+\s+[\d.]+\s+Tf", fluxo))
            if not marcas:
                return
            fim = marcas[-1].end()
            documento.update_stream(
                xref, fluxo[:fim] + (" %.3f Tw" % extra).encode("latin-1") + fluxo[fim:])
        except Exception:
            traceback.print_exc()   # sem espacamento extra, o texto ainda fica correto

    @staticmethod
    def espaco_extra(texto, medir, largura_alvo):
        """Espaco a acrescentar em cada intervalo para a linha manter a largura
        que tinha no documento (o que preserva linhas justificadas).

        `medir` e a funcao que da a largura de um texto na fonte usada.
        Devolve 0,0 quando nao ha o que espalhar - texto de uma palavra so,
        texto que ja ficou mais largo que o original, ou folga tao grande que
        espalhar deixaria as palavras longe demais umas das outras.
        """
        partes = texto.split(" ")
        if len(partes) < 2 or largura_alvo <= 0:
            return 0.0
        try:
            natural = medir(texto)
            espaco = medir(" ")
        except Exception:
            return 0.0
        folga = largura_alvo - natural
        if folga <= 0.2 or espaco <= 0:
            return 0.0
        extra = folga / (len(partes) - 1)
        return extra if extra <= LIMITE_ESPACO * espaco else 0.0

    @staticmethod
    def passa_da_margem(texto, fonte, tamanho, largura_disponivel):
        """Diz se o texto novo, no corpo original, ultrapassa a margem da pagina."""
        if largura_disponivel <= 0:
            return True
        try:
            return fitz.get_text_length(texto, fontname=fonte, fontsize=tamanho) > largura_disponivel
        except Exception:
            return False

    # ------------------------------------------------ localizar/substituir --
    def localizar_substituir(self):
        if self.doc is None:
            messagebox.showinfo(APP_NOME, "Abra um PDF primeiro.")
            return
        dlg = SubstituirDialog(self)
        if not dlg.resultado:
            return
        procurar, trocar, todas = dlg.resultado
        if not procurar:
            return
        self.guardar_undo()
        total = 0
        paginas = range(self.doc.page_count) if todas else [self.pagina_atual]
        for n in paginas:
            pagina = self.doc[n]
            pares = [(t, t["text"].replace(procurar, trocar))
                     for t in self.extrair_trechos(pagina) if procurar in t["text"]]
            if pares:
                self.substituir_trechos(pagina, pares)
                total += len(pares)
        if total:
            self.modificado = True
            self.carregar_pagina()
            self._atualizar_titulo()
            messagebox.showinfo(APP_NOME, "%d trecho(s) alterado(s)." % total)
        else:
            if self.pilha_undo:
                self.pilha_undo.pop()
            messagebox.showinfo(APP_NOME, "Texto '%s' nao encontrado." % procurar)

    # ----------------------------------------------- acabamento do documento --
    # Acoes sobre o documento inteiro (ver acabamento.py). Todas podem ser
    # desfeitas com Ctrl+Z, como as edicoes de texto.
    def _precisa_documento(self):
        if self.doc is None:
            messagebox.showinfo(APP_NOME, "Abra um PDF primeiro.")
            return False
        return True

    def _acabar(self, funcao, mensagem):
        """Executa `funcao(doc)` guardando o desfazer; `mensagem` recebe o retorno."""
        self.guardar_undo()
        try:
            resultado = funcao(self.doc)
        except Exception as exc:
            traceback.print_exc()
            if self.pilha_undo:          # nada mudou: volta ao estado anterior
                self.doc.close()
                self.doc = fitz.open("pdf", self.pilha_undo.pop())
                self.carregar_pagina()
            messagebox.showerror(APP_NOME, "Nao foi possivel concluir:\n\n%s" % exc)
            return
        self.modificado = True
        self.carregar_pagina()
        self._atualizar_titulo()
        self.status(mensagem(resultado) + " Ctrl+Z desfaz.")

    def numerar_paginas(self):
        if not self._precisa_documento():
            return
        valores = FormularioDialog(self, "Numerar paginas", [
            ("formato", "Texto", "texto", "<Pagina> de <Paginas>"),
            ("posicao", "Posicao", "lista", "inferior-centro",
             [(p, p.replace("-", " ")) for p in ac.POSICOES]),
            ("inicio", "Comecar na pagina", "inteiro", 1),
            ("numero", "Primeiro numero", "inteiro", 1),
            ("tamanho", "Tamanho da letra", "real", 10),
            ("cor", "Cor", "cor", "#000000"),
            ("romanos", "Numeros romanos (i, ii, iii...)", "marcar", False),
            ("alternar", "Espelhar nas paginas pares (frente e verso)", "marcar", False),
        ], dica=TEXTO_MARCADORES).resultado
        if not valores:
            return
        self._acabar(lambda doc: ac.numerar_paginas(
            doc, formato=valores["formato"], posicao=valores["posicao"],
            a_partir_da_pagina=valores["inicio"], primeiro_numero=valores["numero"],
            romanos=valores["romanos"], alternar=valores["alternar"],
            tamanho=valores["tamanho"], cor=hex_para_rgb(valores["cor"]),
            caminho=self.caminho),
            lambda n: "%d pagina(s) numerada(s)." % n)

    def carimbar(self):
        if not self._precisa_documento():
            return
        valores = FormularioDialog(self, "Carimbo / marca d'agua", [
            ("texto", "Texto", "texto", "CONFIDENCIAL"),
            ("tamanho", "Tamanho (0 = ajustar a pagina)", "real", 0),
            ("cor", "Cor", "cor", "#bf1a1a"),
            ("opacidade", "Opacidade (%)", "inteiro", 35),
            ("contorno", "Somente o contorno das letras", "marcar", False),
            ("onde", "Paginas", "lista", "todas",
             [("todas", "todas"), ("atual", "so a pagina atual")]),
        ], dica=TEXTO_MARCADORES).resultado
        if not valores or not valores["texto"].strip():
            return
        paginas = [self.pagina_atual] if valores["onde"] == "atual" else None
        self._acabar(lambda doc: ac.carimbar(
            doc, valores["texto"], tamanho=valores["tamanho"] or None,
            cor=hex_para_rgb(valores["cor"]),
            opacidade=max(5, min(100, valores["opacidade"])) / 100.0,
            contorno=valores["contorno"], paginas=paginas, caminho=self.caminho),
            lambda n: "Carimbo aplicado em %d pagina(s)." % n)

    def papel_timbrado(self):
        if not self._precisa_documento():
            return
        caminho = filedialog.askopenfilename(
            title="PDF do papel timbrado (fundo)",
            filetypes=[("Arquivos PDF", "*.pdf")] + TIPOS_IMAGEM)
        if not caminho:
            return
        fundo = self._abrir_como_pdf(caminho)
        if fundo is None:
            return
        valores = FormularioDialog(self, "Papel timbrado", [
            ("repeticao", "Quando o fundo tiver menos paginas", "lista", "ultima",
             [("ultima", "repetir a ultima pagina do fundo"),
              ("todas", "recomecar do inicio do fundo"),
              ("nenhuma", "deixar as demais sem fundo")]),
            ("inicio", "Comecar na pagina", "inteiro", 1),
            ("por_cima", "Colocar por cima do conteudo (em vez de atras)", "marcar", False),
        ], dica="O fundo tem %d pagina(s)." % fundo.page_count).resultado
        if valores:
            self._acabar(lambda doc: ac.aplicar_fundo(
                doc, fundo, repeticao=valores["repeticao"], por_cima=valores["por_cima"],
                a_partir_da_pagina=valores["inicio"]),
                lambda n: "Papel timbrado aplicado em %d pagina(s)." % n)
        fundo.close()

    def _juntar(self, titulo, varios, funcao, mensagem):
        if not self._precisa_documento():
            return
        tipos = [("PDF e imagens", "*.pdf " + TIPOS_IMAGEM[0][1])]
        if varios:
            caminhos = list(filedialog.askopenfilenames(title=titulo, filetypes=tipos))
        else:
            caminho = filedialog.askopenfilename(title=titulo, filetypes=tipos)
            caminhos = [caminho] if caminho else []
        outros = []
        for caminho in caminhos:
            outro = self._abrir_como_pdf(caminho)
            if outro is None:
                break
            outros.append(outro)
        else:
            if outros:
                def juntar_todos(doc):
                    return sum(funcao(doc, outro) for outro in outros)
                self._acabar(juntar_todos, mensagem)
        for outro in outros:
            outro.close()

    def inserir_capa(self):
        self._juntar("Escolha a capa (PDF ou imagem)", False, ac.inserir_capa,
                     lambda n: "Capa inserida (%d pagina(s))." % n)

    def anexar_arquivos(self):
        self._juntar("Escolha os arquivos a anexar (PDF ou imagens)", True,
                     ac.anexar_ao_final,
                     lambda n: "%d pagina(s) anexada(s) ao final." % n)

    def propriedades(self):
        if not self._precisa_documento():
            return
        meta = self.doc.metadata or {}
        valores = FormularioDialog(self, "Propriedades do documento", [
            ("titulo", "Titulo", "texto", meta.get("title", "")),
            ("autor", "Autor", "texto", meta.get("author", "")),
            ("assunto", "Assunto", "texto", meta.get("subject", "")),
            ("chaves", "Palavras-chave", "texto", meta.get("keywords", "")),
        ], dica="Aparecem nas propriedades do arquivo e na busca do sistema.\n"
                + TEXTO_MARCADORES).resultado
        if valores:
            self._acabar(lambda doc: ac.definir_propriedades(
                doc, titulo=valores["titulo"], autor=valores["autor"],
                assunto=valores["assunto"], palavras_chave=valores["chaves"],
                caminho=self.caminho),
                lambda _: "Propriedades atualizadas.")

    def salvar_protegido(self):
        if not self._precisa_documento():
            return
        valores = FormularioDialog(self, "Salvar copia protegida", [
            ("abrir", "Senha para abrir (opcional)", "senha", ""),
            ("dono", "Senha do dono (libera tudo)", "senha", ""),
            ("dono2", "Repita a senha do dono", "senha", ""),
            ("imprimir", "Permitir imprimir", "marcar", True),
            ("copiar", "Permitir copiar texto e imagens", "marcar", False),
            ("alterar", "Permitir alterar o documento", "marcar", False),
            ("anotar", "Permitir comentarios e anotacoes", "marcar", False),
        ], dica="Criptografia AES de 256 bits. As permissoes valem para quem\n"
                "abre o arquivo sem a senha do dono.").resultado
        if not valores:
            return
        if not valores["dono"]:
            messagebox.showerror(APP_NOME, "Informe a senha do dono.")
            return
        if valores["dono"] != valores["dono2"]:
            messagebox.showerror(APP_NOME, "As duas senhas do dono nao conferem.")
            return
        raiz, _ = os.path.splitext(os.path.basename(self.caminho or "documento.pdf"))
        destino = filedialog.asksaveasfilename(
            title="Salvar copia protegida", defaultextension=".pdf",
            initialfile=raiz + "_protegido.pdf", filetypes=[("Arquivos PDF", "*.pdf")])
        if not destino:
            return
        if self.caminho and os.path.abspath(destino) == os.path.abspath(self.caminho):
            messagebox.showerror(APP_NOME, "Escolha outro nome: a copia protegida nao pode "
                                           "substituir o arquivo que esta aberto.")
            return
        opcoes = ac.opcoes_de_protecao(
            valores["dono"], valores["abrir"], imprimir=valores["imprimir"],
            copiar=valores["copiar"], alterar=valores["alterar"], anotar=valores["anotar"])
        try:
            # a copia vai protegida; o documento aberto continua o mesmo
            copia = fitz.open("pdf", self.doc.tobytes())
            try:
                copia.subset_fonts()
            except Exception:
                pass
            copia.save(destino, garbage=4, deflate=True, **opcoes)
            copia.close()
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror(APP_NOME, "Erro ao salvar:\n\n%s" % exc)
            return
        self.status("Copia protegida salva em: %s" % destino)
        messagebox.showinfo(APP_NOME, "Copia protegida salva em:\n\n%s" % destino)

    def exportar_imagens(self):
        if not self._precisa_documento():
            return
        valores = FormularioDialog(self, "Exportar paginas como imagem", [
            ("formato", "Formato", "lista", "png",
             [("png", "PNG (um arquivo por pagina)"), ("jpg", "JPEG (um arquivo por pagina)"),
              ("tif", "TIFF (um arquivo com todas as paginas)")]),
            ("dpi", "Resolucao (dpi)", "inteiro", 150),
            ("onde", "Paginas", "lista", "todas",
             [("todas", "todas"), ("atual", "so a pagina atual")]),
        ]).resultado
        if not valores:
            return
        pasta = filedialog.askdirectory(title="Pasta onde gravar as imagens")
        if not pasta:
            return
        nome = os.path.splitext(os.path.basename(self.caminho or "documento.pdf"))[0]
        paginas = [self.pagina_atual] if valores["onde"] == "atual" else None
        self.status("Exportando...")
        try:
            criados = ac.exportar_imagens(self.doc, pasta, nome, formato=valores["formato"],
                                          dpi=max(36, min(600, valores["dpi"])),
                                          paginas=paginas)
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror(APP_NOME, "Erro ao exportar:\n\n%s" % exc)
            return
        self.status("%d imagem(ns) gravada(s) em %s" % (len(criados), pasta))
        messagebox.showinfo(APP_NOME, "%d arquivo(s) gravado(s) em:\n\n%s" % (len(criados), pasta))


# --------------------------------------------------------------------------
# Caixas de dialogo auxiliares
# --------------------------------------------------------------------------
class SenhaDialog(tk.Toplevel):
    def __init__(self, pai):
        super().__init__(pai)
        self.title("Senha do PDF")
        self.resizable(False, False)
        self.resultado = None
        ttk.Label(self, text="Este PDF esta protegido. Informe a senha:", padding=10).pack()
        self.ent = ttk.Entry(self, show="*", width=32)
        self.ent.pack(padx=10)
        quadro = ttk.Frame(self, padding=10)
        quadro.pack()
        ttk.Button(quadro, text="OK", command=self.ok).pack(side="left", padx=4)
        ttk.Button(quadro, text="Cancelar", command=self.destroy).pack(side="left")
        self.ent.bind("<Return>", lambda e: self.ok())
        self.ent.focus_set()
        self.transient(pai)
        self.grab_set()
        pai.wait_window(self)

    def ok(self):
        self.resultado = self.ent.get()
        self.destroy()


class SubstituirDialog(tk.Toplevel):
    def __init__(self, pai):
        super().__init__(pai)
        self.title("Localizar e substituir")
        self.resizable(False, False)
        self.resultado = None
        corpo = ttk.Frame(self, padding=12)
        corpo.pack()
        ttk.Label(corpo, text="Localizar:").grid(row=0, column=0, sticky="w")
        self.e1 = ttk.Entry(corpo, width=38)
        self.e1.grid(row=0, column=1, pady=3)
        ttk.Label(corpo, text="Substituir por:").grid(row=1, column=0, sticky="w")
        self.e2 = ttk.Entry(corpo, width=38)
        self.e2.grid(row=1, column=1, pady=3)
        self.var_todas = tk.BooleanVar(value=True)
        ttk.Checkbutton(corpo, text="Em todas as paginas",
                        variable=self.var_todas).grid(row=2, column=1, sticky="w", pady=(4, 0))
        quadro = ttk.Frame(self, padding=(12, 0, 12, 12))
        quadro.pack(fill="x")
        ttk.Button(quadro, text="Substituir", command=self.ok).pack(side="right", padx=4)
        ttk.Button(quadro, text="Cancelar", command=self.destroy).pack(side="right")
        self.e1.focus_set()
        self.transient(pai)
        self.grab_set()
        pai.wait_window(self)

    def ok(self):
        self.resultado = (self.e1.get(), self.e2.get(), self.var_todas.get())
        self.destroy()


TEXTO_MARCADORES = ("Marcadores: <Pagina> <Paginas> <Titulo> <Autor> <Assunto>\n"
                    "<Arquivo> <Data> <Hora>")


class FormularioDialog(tk.Toplevel):
    """Caixa de dialogo montada a partir de uma lista de campos.

    Cada campo e (chave, rotulo, tipo, padrao) ou, para "lista",
    (chave, rotulo, "lista", padrao, [(valor, texto), ...]). Tipos: texto,
    senha, inteiro, real, lista, marcar e cor (guardada como "#rrggbb").
    `resultado` fica com {chave: valor}, ou None se a pessoa cancelar.
    """

    def __init__(self, pai, titulo, campos, dica=None):
        super().__init__(pai)
        self.title(titulo)
        self.resizable(False, False)
        self.resultado = None
        self.campos = campos
        self.leitores = {}
        corpo = ttk.Frame(self, padding=12)
        corpo.pack(fill="both")
        primeiro = None
        for linha, campo in enumerate(campos):
            chave, rotulo, tipo, padrao = campo[:4]
            if tipo == "marcar":
                var = tk.BooleanVar(value=bool(padrao))
                ttk.Checkbutton(corpo, text=rotulo, variable=var).grid(
                    row=linha, column=0, columnspan=2, sticky="w", pady=2)
                self.leitores[chave] = var.get
                continue
            ttk.Label(corpo, text=rotulo + ":").grid(row=linha, column=0, sticky="w",
                                                      padx=(0, 8), pady=3)
            if tipo == "lista":
                opcoes = campo[4]
                textos = [t for _, t in opcoes]
                var = tk.StringVar(value=dict(opcoes).get(padrao, textos[0]))
                widget = ttk.Combobox(corpo, textvariable=var, values=textos,
                                      state="readonly", width=36)
                self.leitores[chave] = (lambda v=var, o=opcoes:
                                        next(val for val, t in o if t == v.get()))
            elif tipo == "cor":
                var = tk.StringVar(value=padrao)
                widget = tk.Button(corpo, width=6, bg=padrao, activebackground=padrao,
                                   relief="groove")
                widget.config(command=lambda v=var, b=widget: self._escolher_cor(v, b))
                self.leitores[chave] = var.get
                widget.grid(row=linha, column=1, sticky="w", pady=3)
                continue
            else:
                var = tk.StringVar(value=str(padrao))
                widget = ttk.Entry(corpo, textvariable=var, width=38,
                                   show="*" if tipo == "senha" else "")
                if tipo == "inteiro":
                    self.leitores[chave] = lambda v=var, r=rotulo: self._numero(v, r, int)
                elif tipo == "real":
                    self.leitores[chave] = lambda v=var, r=rotulo: self._numero(v, r, float)
                else:
                    self.leitores[chave] = var.get
            widget.grid(row=linha, column=1, sticky="we", pady=3)
            primeiro = primeiro or widget
        if dica:
            ttk.Label(corpo, text=dica, foreground="#555", justify="left").grid(
                row=len(campos), column=0, columnspan=2, sticky="w", pady=(8, 0))
        quadro = ttk.Frame(self, padding=(12, 0, 12, 12))
        quadro.pack(fill="x")
        ttk.Button(quadro, text="OK", command=self.ok).pack(side="right", padx=4)
        ttk.Button(quadro, text="Cancelar", command=self.destroy).pack(side="right")
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())
        if primeiro is not None:
            primeiro.focus_set()
        self.transient(pai)
        self.grab_set()
        pai.wait_window(self)

    def _escolher_cor(self, var, botao):
        escolhida = colorchooser.askcolor(color=var.get(), parent=self)[1]
        if escolhida:
            var.set(escolhida)
            botao.config(bg=escolhida, activebackground=escolhida)

    @staticmethod
    def _numero(var, rotulo, tipo):
        try:
            return tipo(var.get().replace(",", "."))
        except ValueError:
            raise ValueError("'%s' precisa ser um numero." % rotulo)

    def ok(self):
        try:
            self.resultado = {chave: ler() for chave, ler in self.leitores.items()}
        except ValueError as exc:
            messagebox.showerror(APP_NOME, str(exc), parent=self)
            return
        self.destroy()


def main():
    EditorPDF().mainloop()


if __name__ == "__main__":
    main()
