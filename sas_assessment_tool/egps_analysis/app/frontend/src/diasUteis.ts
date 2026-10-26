// Dias úteis (seg–sex menos feriados nacionais BR) e formatação de datas para a
// Gestão de EGPs/Inputs. Timezone de referência: America/Sao_Paulo.
//
// FERIADOS CONFIGURÁVEIS: a lista abaixo cobre 2025–2027 (fixos + móveis já resolvidos).
// Para estender/ajustar, edite aqui — ou, no plug real, alimente via
// GestaoDataSource.getHolidays (ex.: tabela Delta de feriados).

export const FERIADOS_BR: string[] = [
  // 2025
  "2025-01-01", "2025-03-03", "2025-03-04", "2025-04-18", "2025-04-21", "2025-05-01",
  "2025-06-19", "2025-09-07", "2025-10-12", "2025-11-02", "2025-11-15", "2025-11-20", "2025-12-25",
  // 2026
  "2026-01-01", "2026-02-16", "2026-02-17", "2026-04-03", "2026-04-21", "2026-05-01",
  "2026-06-04", "2026-09-07", "2026-10-12", "2026-11-02", "2026-11-15", "2026-11-20", "2026-12-25",
  // 2027
  "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-26", "2027-04-21", "2027-05-01",
  "2027-05-27", "2027-09-07", "2027-10-12", "2027-11-02", "2027-11-15", "2027-11-20", "2027-12-25",
];

// "YYYY-MM-DD" de HOJE em America/Sao_Paulo (en-CA formata exatamente assim).
export const hojeSP = (): string =>
  new Date().toLocaleDateString("en-CA", { timeZone: "America/Sao_Paulo" });

// Nº de dias ÚTEIS entre inicio e fim (ISO "YYYY-MM-DD"), inclusivos nas duas pontas.
// inicio ausente -> null ("—" na UI); fim < inicio -> 0. Datas ISO comparam como string.
export function diasUteis(
  inicio: string | null | undefined,
  fim: string,
  feriados: readonly string[] = FERIADOS_BR,
): number | null {
  if (!inicio) return null;
  if (fim < inicio) return 0;
  const fer = new Set(feriados);
  let n = 0;
  // itera em UTC ao meio-dia (imune a DST); limites já são date-only
  const d = new Date(`${inicio}T12:00:00Z`);
  const end = new Date(`${fim}T12:00:00Z`);
  while (d <= end) {
    const dow = d.getUTCDay();
    const iso = d.toISOString().slice(0, 10);
    if (dow !== 0 && dow !== 6 && !fer.has(iso)) n++;
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return n;
}

// ISO "YYYY-MM-DD" -> "dd/mm/aaaa" (ou "dd/mm/aa" com short). Vazio -> "—".
export function fmtBR(iso: string | null | undefined, short = false): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${short ? y.slice(2) : y}`;
}

// Timestamp do banco -> "dd/mm/aa HH:MM" em America/Sao_Paulo (ou "dd/mm/aaaa HH:MM"
// sem short). Vazio -> "—"; formato inesperado -> string crua (não engole o dado).
//
// POR QUE CONVERTER: todo timestamp do painel é gravado com `current_timestamp()` do SQL
// warehouse, que roda em **UTC**, e persistido como STRING sem sufixo de zona
// ("2026-07-27 19:51:38.841"). Exibir a hora crua mostrava +3h (comentário das 16:51
// aparecia como 19:51). A conversão fica na EXIBIÇÃO, não na escrita: o banco segue com
// uma convenção única (tudo UTC) e as linhas antigas passam a aparecer certas também.
// Campos date-only (Com BV, datas da Gestão) NÃO passam por aqui — já são data SP; use fmtBR.
const TS_SP = new Intl.DateTimeFormat("en-GB", {
  timeZone: "America/Sao_Paulo",
  hourCycle: "h23",
  year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});

export function fmtTsBR(ts: string | null | undefined, short = true): string {
  if (!ts) return "—";
  const s = ts.trim();
  // Com sufixo de zona explícito (…Z / …-03:00) o próprio Date resolve; sem sufixo é UTC
  // implícito e montamos em UTC no braço (não deixamos o Date adotar o fuso do browser).
  let d: Date;
  if (/(z|[+-]\d{2}:?\d{2})$/i.test(s)) {
    d = new Date(s.replace(" ", "T"));
  } else {
    const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(s);
    if (!m) return ts;
    d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] ?? 0)));
  }
  if (Number.isNaN(d.getTime())) return ts;
  const p: Record<string, string> = {};
  for (const { type, value } of TS_SP.formatToParts(d)) p[type] = value;
  return `${p.day}/${p.month}/${short ? p.year.slice(2) : p.year} ${p.hour}:${p.minute}`;
}

// Dia útil? (seg–sex e não feriado). ISO "YYYY-MM-DD".
export function ehDiaUtil(data: string, feriados: readonly string[] = FERIADOS_BR): boolean {
  const dow = new Date(`${data}T12:00:00Z`).getUTCDay();
  return dow !== 0 && dow !== 6 && !feriados.includes(data);
}

// Total de dias úteis que o switch "Com BV" ficou ON, a partir do log de eventos.
// `eventos` em ordem ASCENDENTE por data; `comBv` = estado APÓS o evento.
// Intervalo fechado [entrega, retorno): o dia de retorno NÃO conta (mesmo dia = 0).
// Intervalo aberto (ainda ON) [entrega, hoje]: hoje conta (a bola ainda está com o BV).
// Eventos redundantes (ON sobre ON, OFF sobre OFF) são ignorados.
export function diasEmValidacaoBV(
  eventos: { comBv: boolean; data: string }[],
  hoje: string,
  feriados: readonly string[] = FERIADOS_BR,
): number {
  let total = 0;
  let abertoDesde: string | null = null;
  for (const ev of eventos) {
    if (ev.comBv && abertoDesde === null) {
      abertoDesde = ev.data;
    } else if (!ev.comBv && abertoDesde !== null) {
      const d = diasUteis(abertoDesde, ev.data, feriados) ?? 0;      // inclusivo nas 2 pontas
      total += Math.max(0, d - (ehDiaUtil(ev.data, feriados) ? 1 : 0)); // exclui o dia de retorno
      abertoDesde = null;
    }
  }
  if (abertoDesde !== null) total += diasUteis(abertoDesde, hoje, feriados) ?? 0;
  return total;
}
