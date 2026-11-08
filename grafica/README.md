# Motor da gráfica

Transforma o livro do site no PDF/X-1a do manual da Meta Brasil, mantendo a diagramação idêntica à pré-visualização.

## Como funciona

O PDF/X-1a não aceita transparência, e o layout do site usa bastante (sombras das fotos, textos com opacidade, fios translúcidos). Achatar tudo transformaria cada página numa imagem, com o texto borrado. Por isso o livro é impresso em duas camadas, a partir da mesma página `/app/livro/imprimir`:

| Camada | URL | Impressão | O que tem |
|---|---|---|---|
| Frente | `?grafica=frente` | sem fundos (`printBackground: false`) | só texto e fotos, em vetor |
| Fundo | `?grafica=fundo` | com fundos | fios, molduras, sombras, ornamentos, QR codes |

As duas camadas se encaixam ao pixel, porque o CSS do modo gráfica (`globals.css`, bloco "Arquivo da gráfica") só muda cor e visibilidade, nunca tamanho ou posição. No modo gráfica o papel é sempre branco, as fotos sempre impressas, e capa, guarda e contracapa saem do miolo. Capa e guarda viram páginas em branco, para nenhuma página trocar de lado nem de número. Quem usa o site nunca vê esse modo.

```
python pipeline.py frente.pdf saida.pdf --fundo fundo.pdf --largura 148 --altura 210 --nome "Nome do livro"
```

Imprime um relatório JSON e sai com código 0 só quando o PDF passou na validação. No servidor, `POST /grafica` com os campos `livro` (frente) e `fundo` faz o mesmo e devolve o PDF, com o relatório no cabeçalho `X-Relatorio-Grafica` (JSON em base64). Se o PDF for reprovado, a resposta é 422 com o relatório.

## Etapas

| Arquivo | O que faz |
|---|---|
| `cores.py` | Cor neutra (texto, legendas) vira só K, com a mesma luminosidade. Cor com matiz passa pelo perfil ICC. Tudo limitado a 280% de tinta (alvo interno de 272%, por causa da recompressão JPEG). |
| `preparar.py` | Camada de frente: reescreve as cores, achata a opacidade constante sobre o papel branco e converte as fotos (P&B vira K, colorida vira CMYK com limite de tinta). Tira os links (no PDF do site, o QR code de cada voz é clicável; o PDF/X-1a não aceita anotações). Máscara ou sombra na frente é erro: elas pertencem ao fundo. |
| `fundo.py` | Desenha o fundo a 450 dpi com o Ghostscript (que resolve a transparência como o navegador) e coloca por baixo da frente, em CMYK. Cinza de verdade (sombras, fios, QR) vira K; o creme das molduras mantém o tom. |
| `acabamento.py` | Formato exato, sangria de 3 mm (branca), TrimBox e BleedBox, marcas de corte e informações de página, tudo em K. |
| `pipeline.py` | Orquestra, roda o Ghostscript (PDF 1.3, OutputIntent, fontes embutidas, 300 dpi, JPEG de qualidade máxima sem subamostragem) e valida. |
| `validar.py` | Confere versão, PDF/X, OutputIntent, fontes, caixas, sangria, espaços de cor, transparência, cobertura de tinta, páginas que viraram imagem, links que sobraram e elementos encostando no corte. |

## Testes

- `teste/imprimir-site.mjs`: com o site rodando em modo dev, imprime a página real num Chrome isolado, com um livro de teste. Gera `site-referencia.pdf` (como o usuário salva), `site-frente.pdf` e `site-fundo.pdf`. Não lê nem altera dados de ninguém.

```
node teste/imprimir-site.mjs http://localhost:3001 teste/site.pdf
python pipeline.py teste/site-frente.pdf teste/site-x1a.pdf --fundo teste/site-fundo.pdf
```

As fotos de teste (`teste/foto-cor.jpg` e `teste/foto-2.jpg`) não vão para o repositório: são fotos pessoais. Coloque duas fotos suas com esses nomes antes de rodar.

- `teste/livro-teste.html`: página sintética com as cores do site, degradê saturado e QR code, sem transparência (camada única).

Para conferir separações: `gs -sDEVICE=tiffsep -r100 -o sep.tif saida.pdf` (o texto deve aparecer só na chapa Black).

## Pendências conhecidas

- O perfil ICC ainda é o FOGRA39 genérico. Trocar quando a UmLivro mandar o real (`ICC_PADRAO` e `CONDICAO` em `pipeline.py`).
- A capa (com lombada) precisa de um arquivo próprio; a especificação depende da gráfica.
- Em produção, quem imprime as duas camadas é um Chromium no servidor (Render), abrindo a página do livro por um link com token. Ainda não implementado: hoje os dados do site ficam no localStorage.
- Fotos muito saturadas perdem intensidade no CMYK (limite físico da tinta). No degradê de teste, o corte de tinta em sombras muito escuras e saturadas cria leves contornos; em fotos reais isso é raro.
