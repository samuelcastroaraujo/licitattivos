import { NextRequest, NextResponse } from 'next/server';

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000';

// O navegador nunca vê o token: só o servidor do painel fala com a API.
async function encaminhar(pedido: NextRequest, contexto: { params: Promise<{ caminho: string[] }> }) {
  const { caminho } = await contexto.params;
  const barra = caminho.join('/');
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
    return new NextResponse(await resposta.text(), {
      status: resposta.status,
      headers: { 'Content-Type': resposta.headers.get('content-type') ?? 'application/json' },
    });
  } catch {
    return NextResponse.json({ detail: 'Backend indisponível.' }, { status: 503 });
  }
}

export const GET = encaminhar;
export const POST = encaminhar;
