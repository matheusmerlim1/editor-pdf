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
import sys
import tempfile
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import pymupdf as fitz
except ImportError:  # compatibilidade com versoes antigas do PyMuPDF
    import fitz

from PIL import Image, ImageTk


APP_NOME = "Editor de PDF"
MAX_UNDO = 25
MARGEM_DIREITA = 5.0          # margem usada para caber o texto novo na pagina
COR_CAIXA = "#c8c8ff"         # cor das caixas de texto detectadas
COR_SELECAO = "#ff0000"       # cor da caixa selecionada


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


def cor_para_rgb(valor):
    """Converte a cor inteira sRGB do PyMuPDF para tupla (r, g, b) de 0 a 1."""
    try:
        return tuple(fitz.sRGB_to_pdf(int(valor)))
    except Exception:
        return (0.0, 0.0, 0.0)


def cor_para_hex(rgb):
    r, g, b = [max(0, min(255, int(round(c * 255)))) for c in rgb]
    return "#%02x%02x%02x" % (r, g, b)


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
        self.pilha_undo = []
        self.modificado = False
        self.img_tk = None

        self._montar_interface()
        self._atualizar_titulo()
        self.protocol("WM_DELETE_WINDOW", self.ao_fechar)

        # Se o programa foi aberto arrastando um PDF sobre o executavel.
        if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".pdf"):
            self.after(200, lambda: self.abrir(sys.argv[1]))

    # ---------------------------------------------------------------- UI --
    def _montar_interface(self):
        estilo = ttk.Style(self)
        try:
            estilo.theme_use("vista")
        except tk.TclError:
            pass

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
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(-1 * (e.delta // 120), "units"))
        painel.add(quadro_pg, weight=3)

        lateral = ttk.Frame(painel)
        painel.add(lateral, weight=1)

        ttk.Label(lateral, text="Textos encontrados na pagina",
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
        ttk.Button(botoes, text="Apagar trecho", command=self.apagar_trecho).pack(side="left")

        # ---- barra de status
        self.var_status = tk.StringVar(value="Abra um arquivo PDF para comecar.")
        ttk.Label(self, textvariable=self.var_status, relief="sunken",
                  anchor="w", padding=(6, 3)).pack(side="bottom", fill="x")

        # atalhos de teclado
        self.bind("<Control-o>", lambda e: self.abrir())
        self.bind("<Control-s>", lambda e: self.salvar())
        self.bind("<Control-z>", lambda e: self.desfazer())
        self.bind("<Control-h>", lambda e: self.localizar_substituir())
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
                filetypes=[("Arquivos PDF", "*.pdf"), ("Todos os arquivos", "*.*")])
        if not caminho:
            return
        try:
            doc = fitz.open(caminho)
        except Exception as exc:
            messagebox.showerror(APP_NOME, "Nao foi possivel abrir o arquivo:\n\n%s" % exc)
            return
        if doc.needs_pass:
            senha = SenhaDialog(self).resultado
            if not senha or not doc.authenticate(senha):
                messagebox.showerror(APP_NOME, "PDF protegido: senha invalida ou nao informada.")
                doc.close()
                return
        if self.doc is not None:
            self.doc.close()
        self.doc = doc
        self.caminho = caminho
        self.pagina_atual = 0
        self.pilha_undo.clear()
        self.modificado = False
        self.carregar_pagina()
        self._atualizar_titulo()
        if sum(len(p.get_text().strip()) for p in self.doc) == 0:
            messagebox.showwarning(
                APP_NOME,
                "Este PDF nao possui texto pesquisavel (provavelmente e um documento\n"
                "digitalizado, formado apenas por imagens).\n\n"
                "Para edita-lo seria necessario reconhecimento optico de caracteres (OCR).")
        self.status("Aberto: %s (%d paginas)" % (caminho, self.doc.page_count))

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
            for t in self.trechos:
                x0, y0, x1, y1 = [v * self.zoom for v in t["bbox"]]
                self.canvas.create_rectangle(x0, y0, x1, y1, outline=COR_CAIXA, tags="caixa")
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
        alvo, menor = None, None
        for i, t in enumerate(self.trechos):
            x0, y0, x1, y1 = t["bbox"]
            if x0 <= x <= x1 and y0 <= y <= y1:
                area = (x1 - x0) * (y1 - y0)
                if menor is None or area < menor:
                    menor, alvo = area, i
        if alvo is not None:
            self.selecionar(alvo)
        else:
            self.status("Nenhum texto nesse ponto. Clique sobre um trecho de texto.")

    def selecionar_da_lista(self, evento=None):
        sel = self.lista.curselection()
        if sel:
            self.selecionar(sel[0], rolar_lista=False)

    def selecionar(self, indice, rolar_lista=True):
        self.selecionado = indice
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

    def aplicar_edicao(self):
        if self.doc is None or self.selecionado is None:
            messagebox.showinfo(APP_NOME, "Selecione um trecho de texto na pagina ou na lista.")
            return
        novo = self.txt_edicao.get("1.0", "end-1c").replace("\r", " ").replace("\n", " ")
        trecho = self.trechos[self.selecionado]
        if novo == trecho["text"]:
            self.status("O texto nao foi alterado.")
            return
        self.guardar_undo()
        try:
            transbordou = self.substituir_trechos(self.doc[self.pagina_atual], [(trecho, novo)])
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror(APP_NOME, "Nao foi possivel aplicar a alteracao:\n\n%s" % exc)
            return
        self.modificado = True
        indice = self.selecionado
        self.carregar_pagina()
        self._atualizar_titulo()
        if indice < len(self.trechos):
            self.selecionar(indice)
        if transbordou:
            self.status("Texto alterado (o corpo %.1f foi mantido, mas o texto passou da "
                        "margem da pagina)." % trecho["size"])
        else:
            self.status("Texto alterado. Use 'Salvar' ou 'Salvar como...' para gravar o PDF.")

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

        `pares` e uma lista de tuplas (trecho, texto_novo). Passar texto vazio
        apenas apaga o trecho.
        """
        if not pares:
            return
        rotacao = pagina.rotation
        desrotacao = pagina.derotation_matrix

        # 1) marca as areas a serem apagadas
        for trecho, _ in pares:
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
        transbordaram = 0
        for trecho, novo in pares:
            if not novo.strip():
                continue
            novo = normalizar_texto(novo)
            ponto = fitz.Point(*trecho["origin"]) * desrotacao
            fonte = trecho["base14"]
            # O corpo da fonte original e sempre mantido. Se o texto novo for
            # mais comprido, ele avanca para a direita em vez de encolher.
            tamanho = trecho["size"]
            if self.passa_da_margem(novo, fonte, tamanho, limite - ponto.x):
                transbordaram += 1
            try:
                pagina.insert_text(ponto, novo, fontname=fonte, fontsize=tamanho,
                                   color=trecho["rgb"], rotate=(360 - rotacao) % 360)
            except Exception:
                # caracteres fora do conjunto latino: reescreve com fonte padrao
                seguro = novo.encode("latin-1", "replace").decode("latin-1")
                pagina.insert_text(ponto, seguro, fontname="helv", fontsize=tamanho,
                                   color=trecho["rgb"], rotate=(360 - rotacao) % 360)
        if rotacao:
            pagina.set_rotation(rotacao)
        return transbordaram

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


def main():
    EditorPDF().mainloop()


if __name__ == "__main__":
    main()
