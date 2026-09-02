<div align="center">

<img src="assets/icone.png" width="110" alt="Editor de PDF">

# Editor de PDF

**Aplicativo de mesa em Python que abre um PDF, identifica o texto existente, permite editá-lo e salvar novamente em PDF.**

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PyMuPDF](https://img.shields.io/badge/PyMuPDF-1.24%2B-1e2952)](https://pymupdf.readthedocs.io/)
[![Licença MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-green.svg)](LICENSE)
[![Executável Windows](https://github.com/SEU-USUARIO/editor-pdf/actions/workflows/build.yml/badge.svg)](https://github.com/SEU-USUARIO/editor-pdf/actions/workflows/build.yml)

[Baixar o executável](https://github.com/SEU-USUARIO/editor-pdf/releases/latest) ·
[Página do projeto](https://SEU-USUARIO.github.io/editor-pdf/) ·
[Como funciona](#como-funciona)

<img src="assets/tela.png" width="880" alt="Tela do Editor de PDF">

</div>

---

## O que ele faz

| Recurso | Descrição |
|---|---|
| **Abrir PDF** | Carrega o arquivo e renderiza as páginas na tela (inclusive PDFs protegidos por senha). |
| **Identificar o texto** | Extrai automaticamente todos os trechos de texto da página, com posição, fonte, tamanho e cor. |
| **Editar** | Clique no texto na própria página (ou escolha na lista lateral) e digite o novo conteúdo. |
| **Localizar e substituir** | Troca uma palavra ou frase em uma página ou no documento inteiro de uma só vez. |
| **Apagar trecho** | Remove um texto do documento sem deixar rastro no arquivo. |
| **Desfazer** | Até 25 níveis de desfazer (`Ctrl+Z`). |
| **Salvar em PDF** | Grava o resultado como um PDF normal, que abre em qualquer leitor. |

Atalhos: `Ctrl+O` abrir · `Ctrl+S` salvar · `Ctrl+Z` desfazer · `Ctrl+H` localizar e substituir · `Page Up` / `Page Down` mudar de página.

## Como usar

1. Clique em **Abrir PDF** e escolha o arquivo.
2. Os trechos de texto reconhecidos aparecem contornados em azul na página e listados à direita.
3. Clique no trecho que deseja alterar — ele fica marcado em vermelho e o texto vai para a caixa de edição.
4. Digite o novo texto e clique em **Aplicar alteração**. A página é atualizada na hora.
5. Clique em **Salvar como...** para gravar o PDF editado.

## Instalação

### Opção 1 — executável pronto (Windows, não precisa instalar Python)

Baixe o `EditorPDF.exe` mais recente em **[Releases](https://github.com/SEU-USUARIO/editor-pdf/releases/latest)** e execute com dois cliques. É um arquivo único e portátil; também é possível arrastar um PDF sobre ele para abrir direto.

### Opção 2 — a partir do código-fonte

```bash
git clone https://github.com/SEU-USUARIO/editor-pdf.git
cd editor-pdf
pip install -r requirements.txt
python editor_pdf.py
```

Requer **Python 3.9 ou superior**. No Linux, o Tkinter pode precisar ser instalado à parte (`sudo apt install python3-tk`).

### Gerar o executável você mesmo

```bash
build_exe.bat            # Windows
```

ou manualmente:

```bash
pyinstaller --noconfirm --onefile --windowed --name EditorPDF ^
    --icon assets/icone.ico --add-data "assets/icone.ico;assets" editor_pdf.py
```

O resultado fica em `dist/EditorPDF.exe` (aproximadamente 53 MB, pois inclui o Python e todas as bibliotecas).

## Como funciona

O PDF não guarda "parágrafos editáveis" como um editor de texto: ele guarda instruções de desenho que posicionam cada grupo de caracteres em uma coordenada da página. Por isso a edição acontece em três passos:

```
1. LEITURA        page.get_text("dict")
                  → cada trecho (span) traz texto, caixa (bbox), origem,
                    fonte, tamanho, cor e estilo (negrito/itálico/serifa)

2. SUBSTITUIÇÃO   add_redact_annot(bbox) + apply_redactions()
                  → apaga apenas os caracteres daquele trecho, preservando
                    imagens e desenhos vetoriais da página
                  insert_text(origem, texto_novo, fonte, tamanho, cor)
                  → escreve o texto novo exatamente sobre a mesma linha-base

3. GRAVAÇÃO       doc.save(destino, garbage=4, deflate=True)
```

A fonte original nem sempre está embutida no arquivo, então o texto novo é reescrito com a fonte **base-14** equivalente (Helvetica, Times ou Courier, nas variações normal/negrito/itálico), escolhida pelo nome e pelos *flags* da fonte original. Se o texto novo ficar largo demais para a página, o corpo da fonte é reduzido apenas o necessário para caber.

Arquivo principal: [`editor_pdf.py`](editor_pdf.py) — a substituição fica em `EditorPDF.substituir_trechos()`.

## Limitações conhecidas

- **PDFs digitalizados** (somente imagem) não têm texto para identificar; seria necessário OCR. O programa avisa quando isso acontece.
- O texto novo é reescrito com fontes base-14, então uma fonte muito característica do documento original não é reproduzida com exatidão.
- A edição é feita por trecho (span), não por parágrafo: textos muito maiores que o original não reorganizam a quebra de linha automaticamente.
- Caracteres fora do conjunto latino-1 (por exemplo alfabetos grego ou cirílico) não são suportados pelas fontes base-14. Travessões e aspas curvas são convertidos automaticamente para equivalentes.

## Estrutura do projeto

```
editor-pdf/
├── editor_pdf.py              programa principal (interface + edição do PDF)
├── requirements.txt           dependências
├── build_exe.bat              gera o dist/EditorPDF.exe
├── assets/                    ícone e imagens
├── docs/                      página do projeto (GitHub Pages)
├── exemplos/gerar_exemplo.py  cria um PDF de teste
└── .github/workflows/         compilação automática do executável
```

## Tecnologias

[PyMuPDF](https://pymupdf.readthedocs.io/) (leitura e edição do PDF) · [Tkinter](https://docs.python.org/3/library/tkinter.html) (interface gráfica) · [Pillow](https://python-pillow.org/) (exibição das páginas) · [PyInstaller](https://pyinstaller.org/) (geração do executável).

## Licença

Distribuído sob a licença [MIT](LICENSE).

---

<div align="center">
Trabalho da disciplina de Sistema de Informação — CEFET
</div>
