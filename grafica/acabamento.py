"""
Sangria, caixas de página e marcas de corte, como pede o manual da Meta
(aba "Marcas e sangrias"): marcas de corte, informações de página e
sangria de 3 a 5 mm em todos os lados.

O livro não tem elementos que vazam a página, então a sangria fica branca.
Mesmo assim ela existe no arquivo, com TrimBox e BleedBox corretas, para o
PDF chegar à gráfica no mesmo padrão de um fechamento feito no InDesign.
"""

import datetime

import pikepdf
from pikepdf import Array, Dictionary, Name

MM = 72 / 25.4

SANGRIA_MM = 3.0
# Distância entre a borda da sangria e o começo da marca de corte, e o tamanho da marca
FOLGA_MARCA_MM = 1.0
TAMANHO_MARCA_MM = 5.0
# Espaço total fora do refile: sangria + folga + marca + respiro
MARGEM_EXTERNA_MM = SANGRIA_MM + FOLGA_MARCA_MM + TAMANHO_MARCA_MM + 4.0


def _caixa(x0, y0, x1, y1):
    return Array([round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)])


def aplicar(pdf, largura_mm, altura_mm, nome_arquivo, sangria_mm=SANGRIA_MM):
    """Aumenta cada página para caber sangria e marcas, centraliza o conteúdo no
    formato final e desenha marcas de corte e informações de página só em K."""
    largura = largura_mm * MM
    altura = altura_mm * MM
    externa = MARGEM_EXTERNA_MM * MM
    sangria = sangria_mm * MM
    folga = (sangria_mm + FOLGA_MARCA_MM) * MM
    marca = TAMANHO_MARCA_MM * MM

    fonte = pdf.make_indirect(Dictionary(
        Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica,
        Encoding=Name.WinAnsiEncoding))

    total = len(pdf.pages)
    data = datetime.date.today().strftime('%d/%m/%Y')
    avisos = []

    for numero, pagina in enumerate(pdf.pages, start=1):
        mx0, my0, mx1, my1 = [float(v) for v in pagina.MediaBox]
        larg_orig, alt_orig = mx1 - mx0, my1 - my0

        # O navegador arredonda o tamanho da página (420 x 594,96 pt em vez de 419,53 x 595,28).
        # Centralizamos o conteúdo no formato exato; diferenças acima de 1 mm viram aviso.
        if abs(larg_orig - largura) > MM or abs(alt_orig - altura) > MM:
            avisos.append(
                f'Página {numero}: {larg_orig / MM:.1f} x {alt_orig / MM:.1f} mm, '
                f'esperado {largura_mm:.0f} x {altura_mm:.0f} mm.')

        dx = externa + (largura - larg_orig) / 2 - mx0
        dy = externa + (altura - alt_orig) / 2 - my0

        # O conteúdo original fica recortado no formato final + sangria
        corte = (externa - sangria, externa - sangria, largura + 2 * sangria, altura + 2 * sangria)
        antes = (f'q {corte[0]:.3f} {corte[1]:.3f} {corte[2]:.3f} {corte[3]:.3f} re W n '
                 f'1 0 0 1 {dx:.3f} {dy:.3f} cm\n').encode()
        depois = b'\nQ\n' + _marcas(externa, largura, altura, folga, marca, numero, total,
                                     nome_arquivo, data)

        pagina.contents_coalesce()
        conteudo = pagina.Contents.read_bytes()
        pagina.Contents = pdf.make_stream(antes + conteudo + depois)

        if '/Resources' not in pagina.obj:
            pagina.obj['/Resources'] = Dictionary()
        recursos = pagina.obj['/Resources']
        if '/Font' not in recursos:
            recursos['/Font'] = Dictionary()
        recursos['/Font']['/LVHInfo'] = fonte

        media = _caixa(0, 0, largura + 2 * externa, altura + 2 * externa)
        pagina.MediaBox = media
        pagina.obj['/CropBox'] = media
        pagina.obj['/BleedBox'] = _caixa(externa - sangria, externa - sangria,
                                         externa + largura + sangria, externa + altura + sangria)
        pagina.obj['/TrimBox'] = _caixa(externa, externa, externa + largura, externa + altura)
        if '/ArtBox' in pagina.obj:
            del pagina.obj['/ArtBox']

    return avisos


def caixas(pdf):
    """Lê as caixas de todas as páginas, para reaplicar depois do Ghostscript."""
    return [{chave: Array(list(p.obj[chave])) for chave in ('/MediaBox', '/BleedBox', '/TrimBox')
             if chave in p.obj} for p in pdf.pages]


def reaplicar_caixas(pdf, lista):
    for pagina, cx in zip(pdf.pages, lista):
        for chave, valor in cx.items():
            pagina.obj[chave] = valor
        pagina.obj['/CropBox'] = cx['/MediaBox']


def _texto_pdf(texto):
    # Helvetica com WinAnsi: acentos em latin1, parênteses escapados
    bruto = texto.encode('cp1252', errors='replace')
    return b'(' + bruto.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)') + b')'


def _marcas(externa, largura, altura, folga, marca, numero, total, nome, data):
    x0, y0 = externa, externa
    x1, y1 = externa + largura, externa + altura
    linhas = []
    for x, y, sx, sy in ((x0, y0, -1, -1), (x1, y0, 1, -1), (x0, y1, -1, 1), (x1, y1, 1, 1)):
        # Marca horizontal, na altura da linha de corte
        linhas.append(f'{x + sx * folga:.3f} {y:.3f} m {x + sx * (folga + marca):.3f} {y:.3f} l S')
        # Marca vertical
        linhas.append(f'{x:.3f} {y + sy * folga:.3f} m {x:.3f} {y + sy * (folga + marca):.3f} l S')

    info = _texto_pdf(f'{nome}   Página {numero} de {total}   {data}')
    return (b'q 0 0 0 1 K 0.25 w 0 J\n' + '\n'.join(linhas).encode() + b'\nQ\n' +
            b'BT /LVHInfo 6 Tf 0 0 0 1 k ' +
            # Ao lado da marca vertical do canto inferior esquerdo, sem encostar nela
            f'{x0 + 6 * MM:.3f} {y0 - folga - marca + 1:.3f} Td '.encode() +
            info + b' Tj ET\n')
