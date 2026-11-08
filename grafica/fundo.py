"""
Camada de fundo do livro: fios, molduras das fotos, sombras, ornamentos e QR codes.

Esses elementos usam transparência no site (sombra suave, cor translúcida), que o
PDF/X-1a não aceita. O Ghostscript desenha cada página do fundo em alta resolução,
com a transparência resolvida exatamente como no navegador, e o resultado vira uma
imagem CMYK colocada por baixo da camada de frente (texto e fotos, em vetor).

Na conversão de cor, o que é neutro (sombras, fios cinza, QR code) vira só K, como
o texto. A passagem do neutro para o colorido é gradual, para não marcar degraus.
"""

import os
import subprocess
import tempfile
import zlib

import numpy as np
from PIL import Image
from pikepdf import Dictionary, Name

# 450 dpi: fios de 1 px e módulos de QR code continuam nítidos, e o arquivo não explode
RESOLUCAO = 450
# Abaixo deste croma é K puro; acima de CROMA_COR, conversão normal pelo perfil.
# Mais estrito que no texto: o creme das molduras (croma perto de 2,5) precisa manter o tom quente,
# enquanto sombras, fios cinza e QR codes (croma perto de 0) continuam só em K
CROMA_NEUTRO = 1.5
CROMA_COR = 4.0
# Pixel com menos que isto de tinta conta como papel branco
TINTA_MINIMA = 2


def rasterizar(caminho_pdf, pasta):
    """Desenha cada página do fundo em RGB, com a transparência já resolvida."""
    subprocess.run(['gs', '-q', '-dNOPAUSE', '-dBATCH', '-sDEVICE=png16m', f'-r{RESOLUCAO}',
                    '-dTextAlphaBits=4', '-dGraphicsAlphaBits=4',
                    f'-sOutputFile={pasta}/fundo%04d.png', caminho_pdf],
                   check=True, capture_output=True)
    return sorted(os.path.join(pasta, n) for n in os.listdir(pasta) if n.startswith('fundo'))


def para_cmyk(rgb, cores):
    """RGB do fundo para CMYK: neutro em K puro, colorido pelo perfil, tudo dentro de 280%."""
    l_estrela, a, b = cores.lab_de_rgb(rgb)
    croma = np.hypot(a, b)
    peso_cor = np.clip((croma - CROMA_NEUTRO) / (CROMA_COR - CROMA_NEUTRO), 0, 1)[..., None]

    so_k = np.zeros(rgb.shape[:2] + (4,), dtype=np.float32)
    so_k[..., 3] = cores.k_para_luminosidade(l_estrela)
    # Branco do papel fica sem tinta nenhuma
    so_k[(rgb >= 254).all(axis=-1)] = 0

    if peso_cor.max() > 0:
        colorido = cores.cores_para_cmyk(rgb).astype(np.float32)
        cmyk = so_k * (1 - peso_cor) + colorido * peso_cor
    else:
        cmyk = so_k
    return cores.limitar_tinta(np.clip(np.round(cmyk), 0, 255).astype(np.uint8))


def aplicar(pdf_frente, caminho_fundo, cores, rel):
    """Coloca o fundo achatado por baixo de cada página da frente."""
    with tempfile.TemporaryDirectory() as pasta:
        imagens = rasterizar(caminho_fundo, pasta)
        if len(imagens) != len(pdf_frente.pages):
            raise RuntimeError(f'Frente com {len(pdf_frente.pages)} páginas e fundo com {len(imagens)}: '
                               'as duas camadas precisam vir da mesma impressão.')
        for pagina, arquivo in zip(pdf_frente.pages, imagens):
            rgb = np.asarray(Image.open(arquivo).convert('RGB'))
            altura_px, largura_px = rgb.shape[:2]

            # Só a área com tinta vira imagem: página sem fio nem moldura não ganha fundo
            com_tinta = (rgb < 255 - TINTA_MINIMA).any(axis=-1)
            if not com_tinta.any():
                continue
            linhas = np.where(com_tinta.any(axis=1))[0]
            colunas = np.where(com_tinta.any(axis=0))[0]
            y0, y1 = int(linhas[0]), int(linhas[-1]) + 1
            x0, x1 = int(colunas[0]), int(colunas[-1]) + 1
            recorte = np.ascontiguousarray(rgb[y0:y1, x0:x1])
            cmyk = para_cmyk(recorte, cores)

            imagem = pdf_frente.make_stream(
                zlib.compress(cmyk.tobytes(), 6),
                Dictionary(Type=Name.XObject, Subtype=Name.Image, Width=x1 - x0, Height=y1 - y0,
                           ColorSpace=Name.DeviceCMYK, BitsPerComponent=8, Filter=Name.FlateDecode))

            mx0, my0, mx1, my1 = [float(v) for v in pagina.MediaBox]
            escala_x = (mx1 - mx0) / largura_px
            escala_y = (my1 - my0) / altura_px
            # Pixels contam de cima para baixo; o PDF, de baixo para cima
            px = mx0 + x0 * escala_x
            py = my1 - y1 * escala_y
            larg = (x1 - x0) * escala_x
            alt = (y1 - y0) * escala_y

            if '/Resources' not in pagina.obj:
                pagina.obj['/Resources'] = Dictionary()
            recursos = pagina.obj['/Resources']
            if '/XObject' not in recursos:
                recursos['/XObject'] = Dictionary()
            recursos['/XObject']['/LVHFundo'] = imagem

            pagina.contents_coalesce()
            conteudo = pagina.Contents.read_bytes()
            antes = f'q {larg:.4f} 0 0 {alt:.4f} {px:.4f} {py:.4f} cm /LVHFundo Do Q\n'.encode()
            pagina.Contents = pdf_frente.make_stream(antes + conteudo)
            rel.fundos += 1
