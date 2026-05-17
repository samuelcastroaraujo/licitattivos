'use client';
import { useEffect, useState, useRef } from 'react';

export interface WarRoomEvent {
  id: string;
  nivel: 'verde' | 'ambar' | 'vermelho';
  motivo: string;
  timestamp: string;
  ack: boolean;
  sugestao_resposta?: string;
}

export function useWarRoom(wsUrl: string) {
  const [events, setEvents] = useState<WarRoomEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    // Cria o som discreto para o alerta vermelho
    if (typeof window !== 'undefined') {
      audioRef.current = new Audio('data:audio/wav;base64,UklGRl9vT19XQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YU');
    }
    
    let pingInterval: NodeJS.Timeout;

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        // Ping-pong a cada 30s (Regra do Desapego)
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30000);
      };

      ws.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data);

          if (data.type === 'pong') return;

          if (data.type === 'sync_state') {
            setEvents(data.events || []);
          } else if (data.nivel) {
            // É um novo evento (broadcast)
            setEvents(prev => [...prev, data as WarRoomEvent]);
            
            if (data.nivel === 'vermelho' && audioRef.current) {
              audioRef.current.play().catch(() => {}); // catch para browsers bloqueando autoplay
            }
          }
        } catch (e) {
          console.error("Erro no WS payload", e);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        clearInterval(pingInterval);
        // Reconnection logic simple
        setTimeout(connect, 5000);
      };
    };

    connect();

    return () => {
      clearInterval(pingInterval);
      wsRef.current?.close();
    };
  }, [wsUrl]);

  const acknowledge = (eventId: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'ack', event_id: eventId }));
    }
    setEvents(prev => prev.map(e => e.id === eventId ? { ...e, ack: true } : e));
  };

  return { connected, events, acknowledge };
}
