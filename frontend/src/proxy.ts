import { NextRequest, NextResponse } from 'next/server';

function iguais(a: string, b: string) {
  if (a.length !== b.length) return false;
  let diferenca = 0;
  for (let i = 0; i < a.length; i++) diferenca |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diferenca === 0;
}

export function proxy(pedido: NextRequest) {
  const senha = process.env.PAINEL_SENHA;
  if (!senha) {
    // Sem senha configurada, o painel só abre em desenvolvimento.
    if (process.env.NODE_ENV !== 'production') return NextResponse.next();
    return new NextResponse('Configure PAINEL_SENHA.', { status: 503 });
  }
  const credencial = pedido.headers.get('authorization')?.split(' ')[1] ?? '';
  const esperada = btoa(`${process.env.PAINEL_USUARIO ?? 'samuel'}:${senha}`);
  if (iguais(credencial, esperada)) return NextResponse.next();
  return new NextResponse('Acesso restrito.', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="LicitAttivos"' },
  });
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] };
