import { NextRequest, NextResponse } from 'next/server';

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000';
// Cabeçalhos da resposta que o navegador precisa ver (download de PDF/DOCX).
const REPASSAR = ['content-type', 'content-disposition', 'content-length'];

// O navegador nunca vê o token: só o servidor do painel fala com a API.
async function encaminhar(pedido: NextRequest, contexto: { params: Promise<{ caminho: string[] }> }) {
  const { caminho } = await contexto.params;
  const barra = caminho.map(encodeURIComponent).join('/');
  const destino = new URL(`${BACKEND}/api/${barra}${caminho.length === 1 ? '/' : ''}`);
  destino.search = pedido.nextUrl.search;
  try {
    const resposta = await fetch(destino, {
      method: pedido.method,
      headers: {
        'Content-Type': pedido.headers.get('content-type') ?? 'application/json',
        'X-API-Token': process.env.API_TOKEN ?? '',
      },
      body: pedido.method === 'GET' ? undefined : await pedido.text(),
      cache: 'no-store',
    });
    const headers = new Headers();
    for (const nome of REPASSAR) {
      const valor = resposta.headers.get(nome);
      if (valor) headers.set(nome, valor);
    }
    // Bytes, não texto: PDF e DOCX passam intactos.
    return new NextResponse(await resposta.arrayBuffer(), { status: resposta.status, headers });
  } catch {
    return NextResponse.json({ detail: 'Backend indisponível.' }, { status: 503 });
  }
}

export const GET = encaminhar;
export const POST = encaminhar;
