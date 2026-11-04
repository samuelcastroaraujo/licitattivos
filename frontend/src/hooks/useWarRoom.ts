'use client';
import { useEffect, useRef, useState } from 'react';

export interface WarRoomEvent {
  id: string;
  nivel: 'verde' | 'ambar' | 'vermelho';
  motivo: string;
  timestamp: string;
  ack: boolean;
  sugestao_resposta?: string;
}

/**
 * Canal da War Room (Agente 8). Sem URL configurada, não conecta: o Agente 8 ainda
 * não está ligado ao pipeline e o navegador não tem o token da API.
 */
export function useWarRoom(wsUrl?: string) {
  const [events, setEvents] = useState<WarRoomEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!wsUrl) return;
    let ping: ReturnType<typeof setInterval> | undefined;
    let religar: ReturnType<typeof setTimeout> | undefined;
    let espera = 5_000;
    let encerrado = false;

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        espera = 5_000;
        ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type: 'ping' })), 30_000);
      };
      ws.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data);
          if (data.type === 'pong') return;
          if (data.type === 'sync_state') setEvents(data.events || []);
          else if (data.nivel) setEvents((prev) => [...prev, data as WarRoomEvent]);
        } catch {
          /* payload inválido: ignora */
        }
      };
      ws.onclose = (evento) => {
        setConnected(false);
        clearInterval(ping);
        // 1008 = token recusado: insistir não resolve.
        if (encerrado || evento.code === 1008) return;
        religar = setTimeout(connect, espera);
        espera = Math.min(espera * 2, 60_000);
      };
    };

    connect();
    return () => {
      encerrado = true;
      clearInterval(ping);
      clearTimeout(religar);
      wsRef.current?.close();
    };
  }, [wsUrl]);

  const acknowledge = (eventId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'ack', event_id: eventId }));
    }
    setEvents((prev) => prev.map((e) => (e.id === eventId ? { ...e, ack: true } : e)));
  };

  return { enabled: Boolean(wsUrl), connected, events, acknowledge };
}
