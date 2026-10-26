// Faixa "dados de HH:MM" do app na AWS (ADR 0005, Fase 1): os dados vêm do Databricks por
// sincronização a cada 15 min, das 8h às 20h. Parada há mais de 1 h no horário comercial, a
// faixa fica vermelha — sincronização que falha não pode passar em silêncio.
import { useEffect, useState } from "react";

const LIMITE_MS = 60 * 60 * 1000;
const SP = "America/Sao_Paulo";

function horarioComercial(agora: Date): boolean {
  const h = Number(new Intl.DateTimeFormat("pt-BR", { hour: "numeric", hourCycle: "h23", timeZone: SP }).format(agora));
  return h >= 8 && h < 20;
}

export default function SincronizacaoBanner({ em }: { em: string }) {
  const [agora, setAgora] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setAgora(new Date()), 60_000);
    return () => window.clearInterval(t);
  }, []);
  const quando = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: SP }).format(new Date(em));
  const atrasada = horarioComercial(agora) && agora.getTime() - new Date(em).getTime() > LIMITE_MS;
  return (
    <div className={atrasada ? "sync-banner sync-banner-atrasada" : "sync-banner"} role="status">
      {atrasada
        ? `Dados desatualizados: a última sincronização foi em ${quando}. Avise a gestão do projeto.`
        : `Dados de ${quando} — atualizados a cada 15 min, das 8h às 20h.`}
    </div>
  );
}
