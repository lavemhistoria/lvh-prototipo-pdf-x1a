"""
Prepara o PDF em RGB (o mesmo que o navegador gera no "Salvar em PDF")
para a gráfica: todas as cores viram CMYK ou K antes do Ghostscript.

Por que fazer isso antes do Ghostscript e não deixar ele converter:
- o Ghostscript converteria o texto marrom em 4 cores (preto composto);
- ele não limita a cobertura de tinta;
- se sobrar transparência, ele transforma a página inteira em imagem.

Transparência: o PDF/X-1a não aceita. Opacidade constante (texto a 80%, por exemplo)
é achatada sobre o branco do papel, que é o que está embaixo da camada de frente.
"""

import zlib

import numpy as np
import pikepdf
from PIL import Image
from pikepdf import Name, Operator, PdfImage

from cores import perfil_de_bytes

OPS_RGB = {'rg': 'k', 'RG': 'K'}
OPS_CINZA = {'g', 'G'}


class Relatorio:
    def __init__(self):
        self.fotos_cmyk = 0
        self.fotos_k = 0
        self.cores_convertidas = 0
        self.opacidades_achatadas = 0
        self.fundos = 0
        self.links_removidos = 0
        self.avisos = []
        self.erros = []

    def erro(self, texto):
        if texto not in self.erros:
            self.erros.append(texto)

    def aviso(self, texto):
        if texto not in self.avisos:
            self.avisos.append(texto)


def _espaco_rgb(cs):
    """True se o espaço de cor é RGB (DeviceRGB ou ICCBased com 3 canais)."""
    if cs is None:
        return False
    if isinstance(cs, pikepdf.Name):
        return cs == Name.DeviceRGB or cs == Name.CalRGB
    if isinstance(cs, pikepdf.Array) and len(cs) > 0:
        tipo = cs[0]
        if tipo == Name.ICCBased:
            return int(cs[1].get('/N', 0)) == 3
        if tipo == Name.CalRGB:
            return True
    return False


def _resolver_cs(nome, recursos):
    if nome in (Name.DeviceRGB, Name.DeviceCMYK, Name.DeviceGray, Name.Pattern):
        return nome
    espacos = recursos.get('/ColorSpace') if recursos is not None else None
    if espacos is not None and nome in espacos:
        return espacos[nome]
    return nome


def _sobre_branco(valores, alfa):
    """Cor RGB com opacidade, pintada sobre papel branco."""
    return [v * alfa + (1 - alfa) for v in valores]


class Estado:
    """Estado gráfico que importa para a cor: espaço, cor atual e opacidade."""

    def __init__(self, alfa_preench=1.0, alfa_traco=1.0):
        self.preench_rgb = False
        self.traco_rgb = False
        self.cor_preench = None  # RGB original (sem achatar), para reemitir se a opacidade mudar
        self.cor_traco = None
        self.alfa_preench = alfa_preench
        self.alfa_traco = alfa_traco

    def copia(self):
        novo = Estado()
        novo.__dict__.update(self.__dict__)
        return novo


class Preparador:
    def __init__(self, pdf, cores):
        self.pdf = pdf
        self.cores = cores
        self.rel = Relatorio()
        self._processados = set()
        # Opacidade original de cada ExtGState, guardada antes de zerarmos a transparência
        self._alfas = {}

    def executar(self):
        for pagina in self.pdf.pages:
            recursos = pagina.obj.get('/Resources')
            self._processar_patterns(recursos)
            self._reescrever_conteudo(pagina, recursos, Estado(), eh_pagina=True)
            if '/Group' in pagina.obj:
                del pagina.obj['/Group']
            self._remover_anotacoes(pagina)
        return self.rel

    def _remover_anotacoes(self, pagina):
        """Tira links e outras anotações: o PDF/X-1a não aceita anotação dentro da página.
        No site, o QR code de cada voz é um link clicável; no papel, quem lê aponta a câmera."""
        anotacoes = pagina.obj.get('/Annots')
        if anotacoes is None:
            return
        restantes = [a for a in anotacoes if str(a.get('/Subtype', '')) in ('/PrinterMark', '/TrapNet')]
        removidas = len(anotacoes) - len(restantes)
        self.rel.links_removidos += removidas
        if restantes:
            pagina.obj['/Annots'] = pikepdf.Array(restantes)
        else:
            del pagina.obj['/Annots']

    def _processar_patterns(self, recursos):
        if recursos is None:
            return
        for _, padrao in (recursos.get('/Pattern') or {}).items():
            if padrao.objgen in self._processados:
                continue
            self._processados.add(padrao.objgen)
            if int(padrao.get('/PatternType', 0)) == 1:
                sub = padrao.get('/Resources')
                self._processar_patterns(sub)
                self._reescrever_conteudo(padrao, sub, Estado())
            else:
                self.rel.aviso('Degradê (shading) em RGB: convertido pelo Ghostscript, sem regra de preto em K.')

    def _alfa_do_estado(self, estado_ext):
        chave = estado_ext.objgen
        if chave not in self._alfas or chave == (0, 0):
            self._alfas[chave] = (float(estado_ext.get('/ca', 1)), float(estado_ext.get('/CA', 1)),
                                  estado_ext.get('/BM'), estado_ext.get('/SMask'))
        return self._alfas[chave]

    def _neutralizar_transparencia(self, estado_ext):
        """Tira opacidade, mesclagem e máscara: o efeito já foi aplicado nas cores."""
        ca, cA, bm, mascara = self._alfa_do_estado(estado_ext)
        if ca < 1 or cA < 1:
            self.rel.opacidades_achatadas += 1
        if '/ca' in estado_ext:
            estado_ext.ca = 1
        if '/CA' in estado_ext:
            estado_ext.CA = 1
        if bm is not None and bm not in (Name.Normal, Name.Compatible):
            if bm != Name.Multiply:
                self.rel.aviso(f'Modo de mesclagem {bm} trocado por normal: conferir o resultado.')
            estado_ext.BM = Name.Normal
        if mascara is not None and mascara != Name('/None'):
            # Sem a máscara, uma sombra suave vira um retângulo chapado: não dá para achatar aqui.
            # O caminho certo é o modo gráfica do site, que manda sombras e máscaras para o fundo
            self.rel.erro('Máscara de transparência (sombra, degradê ou máscara) na camada de frente. '
                          'Use o modo gráfica do site (?grafica=frente e ?grafica=fundo).')

    def _cor(self, op, valores, estado):
        """Instrução de cor CMYK para uma cor RGB, já achatada pela opacidade atual."""
        alfa = estado.alfa_preench if op in ('k', 'sc', 'scn') else estado.alfa_traco
        r, g, b = _sobre_branco(valores, alfa) if alfa < 1 else valores
        self.rel.cores_convertidas += 1
        return list(self.cores.cor_vetorial(r, g, b))

    def _reescrever_conteudo(self, alvo, recursos, estado, eh_pagina=False):
        instrucoes = pikepdf.parse_content_stream(alvo)
        novas = []
        pilha = [estado]
        mudou = False
        for instr in instrucoes:
            if isinstance(instr, pikepdf.ContentStreamInlineImage):
                self.rel.aviso('Imagem embutida no fluxo (inline): não convertida, verificar.')
                novas.append(instr)
                continue
            operandos, op = list(instr.operands), str(instr.operator)
            atual = pilha[-1]

            if op == 'q':
                pilha.append(atual.copia())
            elif op == 'Q' and len(pilha) > 1:
                pilha.pop()
            elif op in OPS_RGB and len(operandos) == 3:
                valores = [float(v) for v in operandos]
                if op == 'rg':
                    atual.cor_preench, atual.preench_rgb = valores, False
                else:
                    atual.cor_traco, atual.traco_rgb = valores, False
                novo_op = OPS_RGB[op]
                novas.append(pikepdf.ContentStreamInstruction(self._cor(novo_op, valores, atual), Operator(novo_op)))
                mudou = True
                continue
            elif op in OPS_CINZA and len(operandos) == 1:
                # Cinza do dispositivo vira K no Ghostscript; com opacidade, achatamos como RGB
                cinza = float(operandos[0])
                alfa = atual.alfa_preench if op == 'g' else atual.alfa_traco
                if alfa < 1:
                    novo_op = 'k' if op == 'g' else 'K'
                    valores = [cinza] * 3
                    if op == 'g':
                        atual.cor_preench = valores
                    else:
                        atual.cor_traco = valores
                    novas.append(pikepdf.ContentStreamInstruction(self._cor(novo_op, valores, atual), Operator(novo_op)))
                    mudou = True
                    continue
            elif op in ('cs', 'CS') and operandos:
                espaco = _resolver_cs(operandos[0], recursos)
                eh_rgb = _espaco_rgb(espaco)
                # Trocar de espaço (para um pattern, por exemplo) esquece a cor RGB anterior
                if op == 'cs':
                    atual.preench_rgb = eh_rgb
                    atual.cor_preench = None
                else:
                    atual.traco_rgb = eh_rgb
                    atual.cor_traco = None
                if eh_rgb:
                    novas.append(pikepdf.ContentStreamInstruction([Name.DeviceCMYK], Operator(op)))
                    mudou = True
                    continue
            elif op in ('sc', 'scn', 'SC', 'SCN'):
                ativo_rgb = atual.preench_rgb if op in ('sc', 'scn') else atual.traco_rgb
                numeros = [float(v) for v in operandos if not isinstance(v, pikepdf.Name)]
                if ativo_rgb and len(numeros) == 3:
                    if op in ('sc', 'scn'):
                        atual.cor_preench = numeros
                    else:
                        atual.cor_traco = numeros
                    novas.append(pikepdf.ContentStreamInstruction(self._cor(op, numeros, atual), Operator(op)))
                    mudou = True
                    continue
            elif op == 'gs' and operandos and recursos is not None:
                estado_ext = (recursos.get('/ExtGState') or {}).get(operandos[0])
                if isinstance(estado_ext, pikepdf.Dictionary):
                    ca, cA, _, _ = self._alfa_do_estado(estado_ext)
                    mudou_alfa = (ca != atual.alfa_preench) or (cA != atual.alfa_traco)
                    if '/ca' in estado_ext or ca < 1:
                        atual.alfa_preench = ca * estado.alfa_preench
                    if '/CA' in estado_ext or cA < 1:
                        atual.alfa_traco = cA * estado.alfa_traco
                    self._neutralizar_transparencia(estado_ext)
                    novas.append(instr)
                    # A cor já escolhida passa a valer com a nova opacidade: reemitimos achatada
                    if mudou_alfa:
                        if atual.cor_preench is not None:
                            novas.append(pikepdf.ContentStreamInstruction(
                                [Name.DeviceCMYK], Operator('cs')))
                            novas.append(pikepdf.ContentStreamInstruction(
                                self._cor('k', atual.cor_preench, atual), Operator('k')))
                        if atual.cor_traco is not None:
                            novas.append(pikepdf.ContentStreamInstruction(
                                self._cor('K', atual.cor_traco, atual), Operator('K')))
                    mudou = True
                    continue
            elif op == 'Do' and operandos and recursos is not None:
                xobj = (recursos.get('/XObject') or {}).get(operandos[0])
                if xobj is not None:
                    self._processar_xobject(xobj, atual)
            elif op == 'sh':
                self.rel.aviso('Degradê (sh) no conteúdo: convertido pelo Ghostscript.')
            novas.append(instr)

        if not mudou:
            return
        dados = pikepdf.unparse_content_stream(novas)
        if eh_pagina:
            alvo.obj.Contents = self.pdf.make_stream(dados)
        else:
            alvo.write(dados)

    def _processar_xobject(self, xobj, estado):
        chave = xobj.objgen
        if chave in self._processados:
            return
        self._processados.add(chave)
        subtipo = xobj.get('/Subtype')
        if subtipo == Name.Image:
            self._converter_imagem(xobj, estado.alfa_preench)
        elif subtipo == Name.Form:
            sub = xobj.get('/Resources')
            self._processar_patterns(sub)
            # O formulário herda a opacidade de quem o desenha (opacidade de grupo no CSS)
            herdado = Estado(estado.alfa_preench, estado.alfa_traco)
            self._reescrever_conteudo(xobj, sub, herdado)
            if '/Group' in xobj:
                del xobj['/Group']

    def _converter_imagem(self, xobj, alfa=1.0):
        if xobj.get('/ImageMask'):
            return  # máscara de um bit, pinta com a cor atual (já convertida)
        cs = xobj.get('/ColorSpace')
        eh_indexado = isinstance(cs, pikepdf.Array) and len(cs) and cs[0] == Name.Indexed
        base = cs[1] if eh_indexado else cs
        mascara = xobj.get('/SMask')
        if not _espaco_rgb(base) and mascara is None and alfa >= 1:
            return  # já está em CMYK ou cinza, sem transparência

        try:
            pil = PdfImage(xobj).as_pil_image()
        except Exception as erro:  # pragma: no cover
            self.rel.aviso(f'Imagem não decodificada ({erro}); ficou para o Ghostscript.')
            return
        if not _espaco_rgb(base):
            self.rel.aviso('Imagem CMYK ou cinza com transparência: verificar.')
            return

        perfil = None
        if isinstance(base, pikepdf.Array) and base[0] == Name.ICCBased:
            perfil = perfil_de_bytes(base[1].read_bytes())

        rgb = np.asarray(pil.convert('RGB')).astype(np.float32)

        # Transparência (SMask e opacidade) não existe no PDF/X-1a: achatamos sobre branco.
        # Na camada de frente, o que está embaixo de uma foto é o papel (a moldura fica no fundo)
        if mascara is not None:
            cobertura = np.asarray(PdfImage(mascara).as_pil_image().convert('L').resize(pil.size)).astype(np.float32) / 255
            del xobj['/SMask']
        else:
            cobertura = np.ones(rgb.shape[:2], dtype=np.float32)
        cobertura *= alfa
        if (cobertura < 1).any():
            rgb = rgb * cobertura[..., None] + 255 * (1 - cobertura[..., None])
            self.rel.opacidades_achatadas += 1
        rgb = np.clip(np.round(rgb), 0, 255).astype(np.uint8)

        if self.cores.eh_neutra(rgb):
            cinza = self.cores.foto_para_k(rgb)
            dados, canais_cs = cinza.tobytes(), Name.DeviceGray
            self.rel.fotos_k += 1
        else:
            cmyk = self.cores.foto_para_cmyk(Image.fromarray(rgb), perfil)
            dados, canais_cs = cmyk.tobytes(), Name.DeviceCMYK
            self.rel.fotos_cmyk += 1

        # Gravamos sem perda (Flate); o Ghostscript recomprime e reduz para 300 dpi depois
        xobj.write(zlib.compress(dados, 6), filter=Name.FlateDecode)
        xobj.ColorSpace = canais_cs
        xobj.BitsPerComponent = 8
        xobj.Width, xobj.Height = pil.size
        for chave in ('/Decode', '/DecodeParms', '/Intent'):
            if chave in xobj:
                del xobj[chave]
