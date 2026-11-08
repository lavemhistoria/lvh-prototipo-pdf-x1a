// Gera o PDF do livro exatamente como o "Salvar em PDF" do site, mas sem janela:
// abre um Chrome isolado, grava um livro de teste no localStorage, abre /app/livro/imprimir
// e imprime com o CSS de impressão do próprio site.
//
// Uso: node imprimir-site.mjs http://localhost:3001 site.pdf
// Gera site-referencia.pdf, site-frente.pdf e site-fundo.pdf
// (o site precisa estar rodando em modo dev; nenhum dado seu é lido ou alterado)

import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const [, , origem = 'http://localhost:3001', saida = 'site-rgb.pdf'] = process.argv
const AQUI = dirname(fileURLToPath(import.meta.url))
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const PORTA = 9333

const SITE = process.env.SITE_DIR || join(process.env.HOME, 'Documents/projetos/la-vem-historia')
const CSS_GRAFICA = (() => {
  try {
    const css = readFileSync(join(SITE, 'src/app/globals.css'), 'utf8')
    const inicio = css.indexOf('/* Arquivo da gráfica')
    return inicio >= 0 ? css.slice(inicio) : ''
  } catch {
    return ''
  }
})()

const foto = nome => `data:image/jpeg;base64,${readFileSync(join(AQUI, nome)).toString('base64')}`

const livro = { id: 'livro-teste', role: 'Mãe', recipientName: 'Tom', recipientGender: 'menino', createdAt: new Date().toISOString(), coverColor: 'verde' }
const agora = new Date().toISOString()
const respostas = {
  1001: { questionId: 1001, text: 'Maria Aparecida da Silva. Todo mundo me chama de Cida desde pequena.', photos: [], updatedAt: agora },
  1002: { questionId: 1002, text: 'Minha mãe era devota de Nossa Senhora Aparecida e prometeu que, se a gravidez corresse bem, a filha levaria o nome dela. Meu pai queria Helena, mas perdeu a discussão antes mesmo de começar.', photos: [foto('foto-cor.jpg')], photoCaptions: ['Eu, aos sete anos'], updatedAt: agora },
  1004: { questionId: 1004, text: 'Meu pai, José, veio de Minas. Minha mãe, Lourdes, nasceu em Petrópolis. Os dois se conheceram num baile de carnaval e casaram no ano seguinte.\n\nEste parágrafo existe para testar a quebra de página e a cor do texto corrido do livro.', photos: [foto('teste-saturado.jpg'), foto('foto-2.jpg')], photoCaptions: ['Teste de cor', 'Meu pai'], updatedAt: agora }
}
const dados = {
  'lvh:books': [livro],
  'lvh:user': { name: 'Cida', email: 'teste@exemplo.com', activeBookId: livro.id },
  [`lvh:answers:${livro.id}`]: respostas
}

const perfil = mkdtempSync(join(tmpdir(), 'lvh-chrome-'))
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORTA}`, `--user-data-dir=${perfil}`, '--no-first-run', 'about:blank'], { stdio: 'ignore' })

const esperar = ms => new Promise(r => setTimeout(r, ms))

try {
  let alvo
  for (let i = 0; i < 50 && !alvo; i++) {
    await esperar(200)
    alvo = await fetch(`http://127.0.0.1:${PORTA}/json/list`).then(r => r.json()).then(l => l.find(t => t.type === 'page')).catch(() => null)
  }
  const ws = new WebSocket(alvo.webSocketDebuggerUrl)
  await new Promise(r => ws.addEventListener('open', r, { once: true }))
  let id = 0
  const pendentes = new Map()
  ws.addEventListener('message', ev => {
    const msg = JSON.parse(ev.data)
    if (msg.id && pendentes.has(msg.id)) { pendentes.get(msg.id)(msg); pendentes.delete(msg.id) }
  })
  const cdp = (method, params = {}) => new Promise(r => { const n = ++id; pendentes.set(n, r); ws.send(JSON.stringify({ id: n, method, params })) })
  const avaliar = async expressao => (await cdp('Runtime.evaluate', { expression: expressao, awaitPromise: true, returnByValue: true })).result?.result?.value

  await cdp('Page.enable')
  await cdp('Page.navigate', { url: `${origem}/entrar` })
  await esperar(4000)
  await avaliar(`(() => { localStorage.clear(); const d = ${JSON.stringify(dados)}; for (const [k, v] of Object.entries(d)) localStorage.setItem(k, JSON.stringify(v)); return true })()`)

  // Três impressões da mesma página: a de referência (como o usuário salva, em papel branco)
  // e as duas camadas do arquivo da gráfica. A frente sai sem fundos: só texto e fotos.
  const imprimir = async (consulta, arquivo, comFundo) => {
    await cdp('Page.navigate', { url: `${origem}/app/livro/imprimir${consulta}` })
    for (let i = 0; i < 60; i++) {
      await esperar(500)
      if (await avaliar(`/\\d+ páginas/.test(document.body.innerText)`)) break
    }
    await esperar(1500)
    // O servidor de dev nem sempre recompila o globals.css a tempo: injetamos o bloco do modo gráfica
    // direto do arquivo, para o teste não depender disso (em produção ele vem no bundle)
    if (consulta && CSS_GRAFICA) {
      await avaliar(`(() => { const s = document.createElement('style'); s.textContent = ${JSON.stringify(CSS_GRAFICA)}; document.head.append(s); return true })()`)
      await esperar(300)
    }
    if (!consulta) {
      await avaliar(`(() => { [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Alterar')?.click(); return true })()`)
      await esperar(800)
      await avaliar(`(() => { [...document.querySelectorAll('[role=radio]')].find(b => b.textContent.includes('Papel branco'))?.click(); return true })()`)
      await esperar(800)
      await avaliar(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); return true })()`)
      await esperar(800)
    }
    const paginas = await avaliar(`document.querySelectorAll('.livro-folha').length`)
    const pdf = await cdp('Page.printToPDF', { preferCSSPageSize: true, printBackground: comFundo })
    writeFileSync(arquivo, Buffer.from(pdf.result.data, 'base64'))
    console.log(`${arquivo}: ${paginas} páginas`)
  }

  const base = saida.replace(/\.pdf$/, '')
  await imprimir('', `${base}-referencia.pdf`, true)
  await imprimir('?grafica=frente', `${base}-frente.pdf`, false)
  await imprimir('?grafica=fundo', `${base}-fundo.pdf`, true)
  ws.close()
} finally {
  chrome.kill()
  await esperar(500)
  rmSync(perfil, { recursive: true, force: true })
}
