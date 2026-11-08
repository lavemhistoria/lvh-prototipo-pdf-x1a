"""
Validação do PDF final antes de ir para a gráfica.

Confere o que o manual da Meta pede e o que o PDF/X-1a exige. Um PDF com
qualquer erro não deve seguir para produção; avisos pedem um olhar humano.

Uso direto: python validar.py arquivo.pdf [--largura 148 --altura 210]
"""

import argparse
import io
import json
import re

import numpy as np
import pikepdf
from PIL import Image
from pikepdf import Name, PdfImage

from acabamento import MM

TAC_MAXIMO = 280.0
# Recompressão JPEG cria picos isolados de poucos pixels; olhamos o percentil 99,9
# e aceitamos uma folga pequena no máximo absoluto
TOLERANCIA_PICO = 15.0


def _tac_imagem(xobj):
    img = PdfImage(xobj)
    pil = img.as_pil_image()
    if pil.mode != 'CMYK':
        return None
    filtros = xobj.get('/Filter')
    filtros = [filtros] if isinstance(filtros, Name) else list(filtros or [])
    a = np.asarray(pil).astype(np.float32)
    # No PDF, o valor do JPEG vale como está (só o /Decode inverte). O Pillow, ao ver o
    # marcador Adobe, inverte por conta própria: desfazemos para ler o que o RIP vai ler.
    if Name.DCTDecode in filtros:
        bruto = Image.open(io.BytesIO(xobj.read_raw_bytes()))
        if bruto.info.get('adobe'):
            a = 255 - a
    decode = xobj.get('/Decode')
    if decode is not None and float(decode[0]) == 1:
        a = 255 - a
    total = a.sum(axis=-1) * 100 / 255
    return float(np.percentile(total, 99.9)), float(total.max())


def _ops_cor(dados):
    """Valores de k/K encontrados no fluxo de conteúdo."""
    return [tuple(float(v) for v in m.groups())
            for m in re.finditer(rb'(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+[kK]\b', dados)]


def _tem_fonte(recursos, vistos=None):
    vistos = vistos if vistos is not None else set()
    if recursos is None:
        return False
    if recursos.get('/Font'):
        return True
    for _, xobj in (recursos.get('/XObject') or {}).items():
        if xobj.objgen in vistos or xobj.get('/Subtype') != Name.Form:
            continue
        vistos.add(xobj.objgen)
        if _tem_fonte(xobj.get('/Resources'), vistos):
            return True
    return False


def _pagina_rasterizada(pagina, media):
    """Página sem nenhuma fonte e com uma imagem do tamanho da página inteira."""
    recursos = pagina.obj.get('/Resources')
    if _tem_fonte(recursos):
        return None
    largura_pol = (media[2] - media[0]) / 72
    altura_pol = (media[3] - media[1]) / 72
    for _, xobj in ((recursos or {}).get('/XObject') or {}).items():
        if xobj.get('/Subtype') != Name.Image:
            continue
        w, h = int(xobj.Width), int(xobj.Height)
        proporcao_pagina = largura_pol / altura_pol
        if abs(w / h - proporcao_pagina) < 0.03 and w / largura_pol > 150:
            return f'{w} x {h} px, cerca de {w / largura_pol:.0f} dpi'
    return None


def validar(caminho, largura_mm=None, altura_mm=None):
    erros, avisos, info = [], [], {}
    pdf = pikepdf.open(caminho)

    info['versao'] = pdf.pdf_version
    info['paginas'] = len(pdf.pages)
    if pdf.pdf_version != '1.3':
        erros.append(f'Versão do PDF {pdf.pdf_version}; o manual pede Acrobat 4 (PDF 1.3).')

    pdfx = str(pdf.docinfo.get('/GTS_PDFXVersion', ''))
    info['pdfx'] = pdfx
    if pdfx != 'PDF/X-1a:2001':
        erros.append(f'GTS_PDFXVersion é "{pdfx}", esperado PDF/X-1a:2001.')
    if str(pdf.docinfo.get('/Trapped', '')) not in ('/False', '/True'):
        erros.append('Trapped precisa ser True ou False no PDF/X-1a.')

    intents = pdf.Root.get('/OutputIntents')
    if not intents:
        erros.append('Sem OutputIntent.')
    else:
        oi = intents[0]
        info['output_intent'] = str(oi.get('/OutputConditionIdentifier', ''))
        if '/DestOutputProfile' not in oi and str(oi.get('/RegistryName', '')) == '':
            erros.append('OutputIntent sem perfil ICC nem registro.')

    if pdf.pages and len(pdf.pages) % 4:
        avisos.append(f'{len(pdf.pages)} página{"s" if len(pdf.pages) > 1 else ""}: livros costumam fechar em múltiplos de 4 '
                      '(confirmar com a gráfica se completam com páginas em branco).')

    tac_imagens, tac_vetores = [], []
    vistos = set()

    def checar_recursos(recursos, onde):
        if recursos is None:
            return
        for nome, fonte in (recursos.get('/Font') or {}).items():
            if fonte.objgen in vistos:
                continue
            vistos.add(fonte.objgen)
            desc = fonte.get('/FontDescriptor')
            if fonte.get('/Subtype') == Name.Type0:
                desc = fonte.DescendantFonts[0].get('/FontDescriptor')
            if fonte.get('/Subtype') == Name.Type3:
                continue
            if desc is None or not any(k in desc for k in ('/FontFile', '/FontFile2', '/FontFile3')):
                erros.append(f'{onde}: fonte {fonte.get("/BaseFont")} não embutida.')
        for nome, estado in (recursos.get('/ExtGState') or {}).items():
            if estado.get('/SMask') not in (None, Name('/None')):
                erros.append(f'{onde}: transparência (SMask) não permitida no PDF/X-1a.')
            for chave in ('/ca', '/CA'):
                if chave in estado and float(estado[chave]) < 1:
                    erros.append(f'{onde}: opacidade {chave}={float(estado[chave])} não permitida no PDF/X-1a.')
            bm = estado.get('/BM')
            if bm is not None and bm not in (Name.Normal, Name.Compatible):
                erros.append(f'{onde}: modo de mesclagem {bm} não permitido no PDF/X-1a.')
        for nome, xobj in (recursos.get('/XObject') or {}).items():
            if xobj.objgen in vistos:
                continue
            vistos.add(xobj.objgen)
            if xobj.get('/Subtype') == Name.Image:
                if xobj.get('/ImageMask'):
                    continue
                if '/SMask' in xobj:
                    erros.append(f'{onde}: imagem {nome} com transparência (SMask).')
                cs = xobj.get('/ColorSpace')
                base = cs[1] if isinstance(cs, pikepdf.Array) and cs[0] == Name.Indexed else cs
                if base not in (Name.DeviceCMYK, Name.DeviceGray):
                    erros.append(f'{onde}: imagem {nome} em {base}, precisa ser CMYK ou cinza.')
                elif base == Name.DeviceCMYK and not isinstance(cs, pikepdf.Array):
                    tac = _tac_imagem(xobj)
                    if tac:
                        tac_imagens.append(tac[1])
                        if tac[0] > TAC_MAXIMO or tac[1] > TAC_MAXIMO + TOLERANCIA_PICO:
                            erros.append(f'{onde}: imagem {nome} com cobertura de tinta '
                                         f'{tac[0]:.0f}% (p99,9) / {tac[1]:.0f}% (máx); limite {TAC_MAXIMO:.0f}%.')
            elif xobj.get('/Subtype') == Name.Form:
                checar_recursos(xobj.get('/Resources'), onde)
                checar_conteudo(xobj.read_bytes(), onde)
        for nome, padrao in (recursos.get('/Pattern') or {}).items():
            if int(padrao.get('/PatternType', 0)) == 1:
                checar_recursos(padrao.get('/Resources'), onde)
                checar_conteudo(padrao.read_bytes(), onde)
        for nome, cs in (recursos.get('/ColorSpace') or {}).items():
            tipo = cs[0] if isinstance(cs, pikepdf.Array) else cs
            if tipo in (Name.DeviceRGB, Name.ICCBased, Name.CalRGB, Name.Lab):
                erros.append(f'{onde}: espaço de cor {tipo} ({nome}) não permitido no PDF/X-1a.')

    def checar_conteudo(dados, onde):
        if re.search(rb'(^|[\s\]])-?[\d.]+\s+-?[\d.]+\s+-?[\d.]+\s+(rg|RG)\b', dados):
            erros.append(f'{onde}: cor RGB no conteúdo (texto ou vetor).')
        for cmyk in _ops_cor(dados):
            total = sum(cmyk) * 100
            tac_vetores.append(total)
            if total > TAC_MAXIMO + 0.5:
                erros.append(f'{onde}: cor chapada {cmyk} soma {total:.0f}% de tinta.')

    for numero, pagina in enumerate(pdf.pages, start=1):
        onde = f'Página {numero}'
        media = [float(v) for v in pagina.MediaBox]
        trim = pagina.obj.get('/TrimBox') or pagina.obj.get('/ArtBox')
        if trim is None:
            erros.append(f'{onde}: sem TrimBox (obrigatória no PDF/X).')
        else:
            t = [float(v) for v in trim]
            if largura_mm and altura_mm:
                lw, lh = (t[2] - t[0]) / MM, (t[3] - t[1]) / MM
                if abs(lw - largura_mm) > 0.3 or abs(lh - altura_mm) > 0.3:
                    erros.append(f'{onde}: formato final {lw:.1f} x {lh:.1f} mm, esperado '
                                 f'{largura_mm} x {altura_mm} mm.')
            bleed = pagina.obj.get('/BleedBox')
            if bleed is None:
                avisos.append(f'{onde}: sem BleedBox (o manual pede sangria de 3 a 5 mm).')
            else:
                b = [float(v) for v in bleed]
                sangria = min(t[0] - b[0], t[1] - b[1], b[2] - t[2], b[3] - t[3]) / MM
                if not (2.9 <= sangria <= 5.1):
                    erros.append(f'{onde}: sangria de {sangria:.1f} mm, o manual pede de 3 a 5 mm.')
                if b[0] < media[0] - 0.01 or b[2] > media[2] + 0.01:
                    erros.append(f'{onde}: BleedBox maior que a MediaBox.')
        # Link ou qualquer anotação dentro da página não passa no PDF/X-1a (marcas de impressora, sim)
        anotacoes = [a for a in pagina.obj.get('/Annots', [])
                     if str(a.get('/Subtype', '')) not in ('/PrinterMark', '/TrapNet')]
        if anotacoes:
            erros.append(f'{onde}: tem {len(anotacoes)} anotaç{"ões" if len(anotacoes) > 1 else "ão"} '
                         '(links, por exemplo), que o PDF/X-1a não aceita.')
        rasterizada = _pagina_rasterizada(pagina, media)
        if rasterizada:
            erros.append(
                f'{onde}: virou uma imagem só ({rasterizada}). Acontece quando o layout usa transparência '
                '(opacidade, sombra, mesclagem): o Ghostscript achata a página e o texto perde a nitidez de vetor.')
        checar_recursos(pagina.obj.get('/Resources'), onde)
        conteudo = b''.join(s.read_bytes() for s in (
            pagina.Contents if isinstance(pagina.Contents, pikepdf.Array) else [pagina.Contents]))
        checar_conteudo(conteudo, onde)

    info['tac_max_imagens'] = round(max(tac_imagens), 1) if tac_imagens else None
    info['tac_max_vetores'] = round(max(tac_vetores), 1) if tac_vetores else None
    # Mensagens repetidas por página viram uma só, com a contagem
    erros = _resumir(erros)
    avisos = _resumir(avisos)
    return {'ok': not erros, 'erros': erros, 'avisos': avisos, 'info': info}


def bordas_sem_sangria(caminho, resolucao=36):
    """Páginas com conteúdo encostando na linha de corte.

    A sangria do livro é branca (nada vaza a página no layout atual). Se algum
    elemento encosta no corte, como uma capa de cor chapada, a guilhotina pode
    deixar um filete branco: o certo seria estender esse elemento 3 mm para fora.
    """
    import subprocess
    import tempfile
    import os

    paginas = []
    with tempfile.TemporaryDirectory() as pasta:
        subprocess.run(['gs', '-q', '-dNOPAUSE', '-dBATCH', '-sDEVICE=pnggray', f'-r{resolucao}',
                        '-dUseTrimBox', f'-sOutputFile={pasta}/p%04d.png', caminho],
                       check=True, capture_output=True)
        for nome in sorted(os.listdir(pasta)):
            a = np.asarray(Image.open(os.path.join(pasta, nome)).convert('L')).astype(float)
            faixa = max(1, round(resolucao / 25.4))  # cerca de 1 mm
            bordas = np.concatenate([a[:faixa].ravel(), a[-faixa:].ravel(),
                                     a[:, :faixa].ravel(), a[:, -faixa:].ravel()])
            # Mais de 20% da borda com tinta visível
            if (bordas < 235).mean() > 0.2:
                paginas.append(int(nome[1:5]))
    return paginas


def _resumir(lista):
    vistos, saida = {}, []
    for item in lista:
        if item not in vistos:
            vistos[item] = 1
            saida.append(item)
    return saida


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('pdf')
    p.add_argument('--largura', type=float)
    p.add_argument('--altura', type=float)
    a = p.parse_args()
    print(json.dumps(validar(a.pdf, a.largura, a.altura), ensure_ascii=False, indent=2))
