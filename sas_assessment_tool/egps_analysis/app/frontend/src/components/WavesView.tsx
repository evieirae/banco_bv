import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { api } from "../api";
import { SEG } from "../pipeline";
import { csvBool, csvDate, csvDownload, csvFromColumns, egpShort } from "../csv";
import { pathFor, spaLinkClick } from "../routes";
import { fmtTsBR } from "../diasUteis";
import { usePodeEscrever } from "../usePodeEscrever";
import type { AppConfig, PrioMes, PrioEgp, PriorizacaoPayload } from "../types";

// Aba "Priorização": plano de ingestão por CAPACIDADE, recorte FIXO (Indicium + dependências,
// todas as áreas). A capacidade (inputs/mês) é persistida no servidor (sas_app_config, default
// 400) e a gestão pode editá-la aqui — o plano é único e muda para todos. Slug /ondas p/
// deep-links. Cards de resumo no topo (migrados no mês / bloqueados / habilitados). Gestão
// também fixa EGP num mês (📌). EGP "Despriorizado e Contabilizado" entra no mês como um EGP
// normal (só as dependências exclusivas dele deixam de ser puxadas — regra no backend).
// Backend: GET /api/priorizacao + PATCH /api/priorizacao/{mes,capacidade}.
const CAP = 400;
const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);

// Mês 1 = julho/2026 (âncora FIXA do plano — não desliza com o mês corrente).
// Prazo da migração: dezembro/2026 — meses do plano além disso ganham alerta "fora do prazo".
const MESES_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const PLAN_START = { y: 2026, m: 6 }; // julho/2026 (m é 0-based)
const DEADLINE = { y: 2026, m: 11 }; // dezembro/2026 (m é 0-based)
const calDate = (mes: number) => new Date(PLAN_START.y, PLAN_START.m + (mes - 1), 1);
const calLabel = (mes: number) => {
  const d = calDate(mes);
  return `${MESES_PT[d.getMonth()]}${d.getFullYear() !== new Date().getFullYear() ? `/${d.getFullYear()}` : ""}`;
};
const foraPrazo = (mes: number) => {
  const d = calDate(mes);
  return d.getFullYear() > DEADLINE.y || (d.getFullYear() === DEADLINE.y && d.getMonth() > DEADLINE.m);
};

interface Props {
  cfg: AppConfig | null;
  onOpenEgp: (projeto: string) => void;
}

export function WavesView({ cfg, onOpenEgp }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<Set<number>>(new Set([1]));
  const isGestao = !!cfg?.is_gestao;
  const isAdmin = !!cfg?.is_admin;
  const pode = usePodeEscrever();
  const [preview, setPreview] = useState<PriorizacaoPayload | null>(null);

  const q = useQuery({
    queryKey: ["priorizacao"],
    queryFn: () => api.priorizacao(),
    placeholderData: keepPreviousData,
  });
  // analistas p/ resolver email -> nome no rótulo (mesmo padrão de GestaoStatusPanel).
  const analistasQ = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas() });
  const nomeDe = (email: string | null | undefined) =>
    email ? (analistasQ.data?.rows.find((a) => a.email === email)?.nome ?? email.split("@")[0]) : "—";
  const snap = q.data;              // snapshot congelado (fonte da verdade da tela)
  const data = preview ?? snap;     // preview (recálculo ao vivo, não salvo) tem precedência
  const meses: PrioMes[] = data?.meses ?? [];
  const resumo = data?.resumo;
  const nMeses = data?.n_meses ?? 0;
  const cap = data?.capacidade ?? CAP; // servidor é a fonte de verdade do teto; CAP é fallback pré-load

  // Contagens dos cards, client-side do MESMO payload (todo o recorte está nos meses).
  // "Concluído" = status terminal: Migrado ou Despriorizado e Contabilizado (mesma régua
  // do headline "X/Y migrados" do funil).
  const allEgps = meses.flatMap((m) => m.egps);
  const nMigrados = allEgps.filter((e) => e.status === "Migrado").length;
  const nDespri = allEgps.filter((e) => e.status === "Despriorizado e Contabilizado").length;
  const concluido = (e: PrioEgp) => e.status === "Migrado" || e.status === "Despriorizado e Contabilizado";

  // Edições LOCAIS (não persistidas até Salvar): pins e capacidade — INSTANTÂNEAS, sem ida ao
  // servidor. Recalcular aplica via /preview; Salvar persiste + fixa o snapshot (admin).
  const [pins, setPins] = useState<Map<string, number | null>>(new Map());
  const [pendingCap, setPendingCap] = useState<number | null>(null);
  // Sujeira medida CONTRA o snapshot: um override que volta ao valor original NÃO conta.
  const snapPin = new Map<string, number | null>();
  (snap?.meses ?? []).forEach((mes) => mes.egps.forEach((e) => snapPin.set(e.projeto, e.mes_pin)));
  const snapCap = snap?.capacidade ?? CAP;
  const realPins = [...pins.entries()].filter(([pj, mv]) => (snapPin.get(pj) ?? null) !== (mv ?? null));
  const capChanged = pendingCap != null && pendingCap !== snapCap;
  const dirty = realPins.length > 0 || capChanged;
  const effPin = (e: PrioEgp) => (pins.has(e.projeto) ? pins.get(e.projeto) ?? null : e.mes_pin);
  const effCap = pendingCap ?? snapCap;
  const editsBody = () => ({ pins: Object.fromEntries(realPins), capacidade: capChanged ? pendingCap : null });
  // Editar invalida uma prévia anterior (ela reflete o último Recalcular, não a edição nova).
  const setPin = (projeto: string, mes: number | null) => {
    setPreview(null);
    setPins((prev) => { const n = new Map(prev); n.set(projeto, mes); return n; });
  };
  const setCapLocal = (v: number) => { setPreview(null); setPendingCap(v); };
  const discard = () => { setPreview(null); setPins(new Map()); setPendingCap(null); };

  // Recalcular = recomputa AO VIVO com as edições locais e mostra como PRÉVIA (não salva).
  const recompute = useMutation({
    mutationFn: () => api.priorizacaoPreview(editsBody()),
    onSuccess: (p) => setPreview(p),
  });
  // Salvar = persiste edições (pins/capacidade) + fixa o snapshot (admin). Limpa o estado local.
  const saveSnap = useMutation({
    mutationFn: () => api.priorizacaoSaveSnapshot(editsBody()),
    onSuccess: () => { discard(); qc.invalidateQueries({ queryKey: ["priorizacao"] }); },
  });
  const busy = recompute.isPending || saveSnap.isPending || q.isFetching;
  // quantos EGPs mudariam de mês na prévia vs. o snapshot atual (só para o aviso)
  const movedCount = (() => {
    if (!preview || !snap) return 0;
    const mMap = (p: PriorizacaoPayload) => {
      const m = new Map<string, number>();
      p.meses.forEach((mes) => mes.egps.forEach((e) => m.set(e.projeto, mes.mes)));
      return m;
    };
    const a = mMap(snap), b = mMap(preview);
    let n = 0;
    new Set([...a.keys(), ...b.keys()]).forEach((pj) => { if (a.get(pj) !== b.get(pj)) n++; });
    return n;
  })();

  const toggle = (m: number) =>
    setOpen((s) => { const n = new Set(s); n.has(m) ? n.delete(m) : n.add(m); return n; });

  // Exporta o PLANO inteiro (todos os meses, aberto ou não): 1 linha por EGP × mês,
  // na ordem exibida (pins primeiro, depois prioridade). Mesmo padrão csv.ts das outras abas.
  const exportCsv = () => {
    const rows = meses.flatMap((m) => m.egps.map((e) => ({ mes: m.mes, e })));
    const calFull = (mes: number) => { const d = calDate(mes); return `${MESES_PT[d.getMonth()]}/${d.getFullYear()}`; };
    csvDownload(`priorizacao_${csvDate()}.csv`, csvFromColumns(rows, [
      { header: "Mês", get: (r) => r.mes },
      { header: "Calendário", get: (r) => calFull(r.mes) },
      { header: "Fora do prazo", get: (r) => csvBool(foraPrazo(r.mes)) },
      { header: "EGP", get: (r) => egpShort(r.e.projeto) },
      { header: "Área", get: (r) => r.e.area ?? "" },
      { header: "Etapa", get: (r) => r.e.etapa ?? "" },
      { header: "Status", get: (r) => r.e.status ?? "" },
      { header: "Concluído", get: (r) => csvBool(concluido(r.e)) },
      { header: "Inputs novos", get: (r) => r.e.n_inputs_novos_vivo ?? r.e.n_inputs_novos },
      { header: "Inputs novos (plano congelado)", get: (r) => r.e.n_inputs_novos },
      { header: "Alimenta", get: (r) => r.e.fan_out },
      { header: "Responsável", get: (r) => r.e.responsavel ?? "" },
      { header: "Bloqueado", get: (r) => csvBool(r.e.bloqueado) },
      { header: "Fixado no mês", get: (r) => r.e.mes_pin ?? "" },
      { header: "Excede capacidade", get: (r) => csvBool(r.e.excede) },
    ]));
  };

  return (
    <div className="waves">
      {cfg?.familias_safra && (
        <p className="muted">
          <b>Inputs contados por família de safras</b>: cargas datadas da mesma tabela ocupam
          UMA vaga, não uma por carga. Quais EGPs caem em cada mês continua congelado como
          foi salvo; os números de input são recalculados a cada abertura, tanto o
          modernizados/total do mês quanto a coluna +Inputs de cada EGP. O total do plano
          congelado, ao lado da data, é o da unidade da época.
        </p>
      )}
      <div className="filters">
        <span className="prio-fixed">
          Recorte fixo: <b>Indicium + dependências</b> · todas as áreas ·{" "}
          {isGestao && pode
            ? <CapControl cap={effCap} busy={busy} onSave={setCapLocal} />
            : <b>{cap}</b>}{" "}
          inputs/mês · prazo <b>dez/2026</b>
        </span>
        <span className="count">
          {q.isFetching ? "calculando…" : data
            ? `${data.n_meses} meses · ${
                data.n_inputs_total != null
                  ? `${(data.n_inputs_modernizados ?? 0).toLocaleString("pt-BR")}/${data.n_inputs_total.toLocaleString("pt-BR")} inputs modernizados`
                  : `${data.n_inputs.toLocaleString("pt-BR")} inputs distintos`
              } · ${data.n_egps} EGPs`
            : ""}
        </span>
        {!preview && snap?.snapshot && (
          <span className="prio-snap" title={`Plano congelado — salvo por ${snap.snapshot.saved_by}`}>
            📌 fixado em {fmtTsBR(snap.snapshot.saved_at, false)} por {(snap.snapshot.saved_by || "").split("@")[0]}
          </span>
        )}
        {/* POST /preview não grava, mas o modo leitura recusa todo POST */}
        {pode && (
          <button className="ghost" onClick={() => recompute.mutate()} disabled={busy}
            title="Recalcula o plano ao vivo com as edições locais (não salva) para pré-visualizar">
            {recompute.isPending ? "recalculando…" : "↻ Recalcular"}
          </button>
        )}
        <button
          className="ghost csv-btn"
          onClick={exportCsv}
          disabled={q.isFetching || meses.length === 0}
          title="Baixar CSV do plano inteiro (1 linha por EGP × mês, na ordem exibida)"
        >
          ⬇ Exportar CSV
        </button>
      </div>

      {(dirty || preview) && (
        <div className="prio-preview-banner">
          {preview
            ? <span><b>Pré-visualização não salva</b>{movedCount ? ` · ${movedCount} EGP(s) mudariam de mês vs. o snapshot` : " · igual ao snapshot atual"}.</span>
            : <span><b>Alterações não aplicadas</b>{realPins.length ? ` · ${realPins.length} pin(s)` : ""}{capChanged ? " · capacidade" : ""} — clique em <b>Recalcular</b> para pré-visualizar.</span>}
          <button className="ghost" onClick={discard} disabled={busy}>Descartar</button>
          {isAdmin && pode
            ? <button className="theme-btn" onClick={() => saveSnap.mutate()} disabled={busy}
                title="Persiste os pins/capacidade e fixa o novo snapshot para todos">
                {saveSnap.isPending ? "Salvando…" : "Salvar prioridade"}
              </button>
            : <span className="muted"> — salvar é restrito a administradores</span>}
        </div>
      )}
      {recompute.isError && <div className="error">Falha ao recalcular: {String(recompute.error)}</div>}
      {saveSnap.isError && <div className="error">Falha ao salvar prioridade: {String(saveSnap.error)}</div>}

      {resumo && (
        <div className="metrics prio-metrics">
          <div className="card ok" title="EGPs do recorte com status Migrado (em produção, validado pela área).">
            <div className="card-value">{nMigrados.toLocaleString("pt-BR")}</div>
            <div className="card-label">Migrados</div>
            <div className="card-desc">status Migrado · {resumo.migrados_mes} neste mês</div>
          </div>
          <div className="card" title="EGPs com status Despriorizado e Contabilizado — saíram do backlog; o esforço já gasto fica contabilizado.">
            <div className="card-value">{nDespri.toLocaleString("pt-BR")}</div>
            <div className="card-label">Despriorizados</div>
            <div className="card-desc">fora do backlog, esforço contabilizado</div>
          </div>
          <div className="card danger" title="Dependem (direta ou transitivamente) de tabela SAS sem produtor mapeado. Destravam quando a tabela for ingerida ou o produtor for identificado.">
            <div className="card-value">{resumo.bloqueados.toLocaleString("pt-BR")}</div>
            <div className="card-label">Bloqueados</div>
            <div className="card-desc">dependem de tabela SAS sem produtor</div>
          </div>
          <div className="card ok" title={`Sem bloqueio de dependência — podem avançar agora. Conta: ${resumo.total} EGPs do recorte − ${resumo.bloqueados} bloqueados.`}>
            <div className="card-value">{resumo.habilitados.toLocaleString("pt-BR")}</div>
            <div className="card-label">Habilitados</div>
            <div className="card-desc">sem bloqueio ({resumo.total} no recorte − bloqueados)</div>
          </div>
        </div>
      )}

      <div className="lin-hint">
        Plano por <b>capacidade</b>: meses de até <b>{cap}</b> inputs distintos a ingerir (Mês 1 = mês corrente). Prioridade:{" "}
        <b>1) viabilidade</b> → <b>2) alavancagem</b> → <b>3) quick win</b>. Input compartilhado conta{" "}
        <b>1×</b> (no 1º mês). A barra de cada mês mostra o <b>avanço</b>: EGPs concluídos (Migrado / Despriorizado e Contabilizado).
        {isGestao ? " Gestão pode fixar EGPs num mês (📌) sem limite — o teto de inputs é guia, não trava." : ""} O plano exibido é um <b>snapshot</b> fixo (os EGPs de cada mês não mudam, mesmo se o total de inputs passar da capacidade); mudanças de plano, pins ou capacidade só entram após <b>Recalcular</b> (e <b>Salvar</b>, admin). A contagem <b>modernizados/total</b> de cada mês é <b>viva</b> — reflete o corpus atual dos EGPs congelados. Clique num EGP p/ abrir na aba EGPs.
      </div>
      {q.error && <div className="error">{String(q.error)}</div>}
      <div className="wave-list">
        {meses.map((m) => {
          const isOpen = open.has(m.mes);
          const done = m.egps.filter(concluido).length;
          const pct = m.n_egps ? Math.round((100 * done) / m.n_egps) : 0;
          const full = m.n_egps > 0 && done === m.n_egps;
          const atrasado = foraPrazo(m.mes);
          return (
            <div key={m.mes} className={`wave-card${atrasado ? " cyc" : ""}`}>
              <div className="wave-top clickable" onClick={() => toggle(m.mes)}>
                <span className="wave-name">{isOpen ? "▾" : "▸"} Mês {m.mes} — {calLabel(m.mes)}</span>
                {atrasado && <span className="pill todo" title="além do prazo de dez/2026">fora do prazo</span>}
                <div className="wave-bar" title={`${done} de ${m.n_egps} EGPs do mês concluídos (Migrado / Despriorizado e Contabilizado)`}>
                  <div className={`wave-fill ${full ? "ok" : "wip"}`} style={{ width: `${pct}%` }} />
                </div>
                <span className={`pill ${full ? "ok" : "wip"}`} title="EGPs do mês já concluídos (Migrado / Despriorizado e Contabilizado)">{done}/{m.n_egps} EGPs concluídos</span>
                {m.n_inputs_total != null && (
                  <span
                    className={`pill ${m.n_inputs_total > 0 && m.n_inputs_modernizados === m.n_inputs_total ? "ok" : "wip"}`}
                    title={`Inputs distintos dos EGPs deste mês (contagem VIVA — total muda quando o corpus ganha inputs; input compartilhado conta no 1º mês em que aparece). Os EGPs do mês seguem congelados no plano, mesmo se o total passar da capacidade-guia (${cap}).`}
                  >
                    {(m.n_inputs_modernizados ?? 0).toLocaleString("pt-BR")}/{m.n_inputs_total.toLocaleString("pt-BR")} inputs modernizados
                  </span>
                )}
              </div>
              {isOpen && (
                <div className="prio-egps">
                  <div className="pe-row pe-head">
                    <div>EGP</div><div>Área</div><div>Etapa</div><div>Status</div>
                    <div className="num">+Inputs</div><div className="num">Alimenta</div><div>Responsável</div><div>Mês</div>
                  </div>
                  {m.egps.map((e) => {
                    const ep = effPin(e);
                    return (
                    <div key={e.projeto} className={`pe-row${ep != null ? " pinned" : ""}`}>
                      <a className="pe-egp" href={pathFor("readiness", e.projeto)}
                        title={`${e.projeto} — clique: abre o EGP · botão do meio/ctrl+clique: nova guia`}
                        onClick={(ev) => spaLinkClick(ev, () => onOpenEgp(e.projeto))}>
                        {ep != null && <span title={`fixado no mês ${ep}`}>📌 </span>}
                        {shortName(e.projeto)}
                        {e.ex_dependencia && <span className="tag exdep" title="Ex-dependência: saiu do recorte Indicium + deps mas fica retida no plano (0 inputs novos; fora da contagem de inputs do mês)."> ex-dependência</span>}
                        {e.bloqueado && <span title="bloqueado por dependência"> 🔒</span>}
                        {e.excede && <span className="pill todo"> excede</span>}
                      </a>
                      <div className="pe-cell">{e.area ?? "—"}</div>
                      <div className="pe-cell" title={e.etapa ?? ""}>{e.etapa ?? "—"}</div>
                      <div className="pe-cell">
                        {e.status
                          ? (SEG[e.status]
                            ? <span className="pe-status" style={{ background: SEG[e.status].bg, color: SEG[e.status].fg }}>{e.status}</span>
                            : e.status)
                          : "—"}
                      </div>
                      <div className="pe-cell num"
                        title={e.n_inputs_novos_vivo != null && e.n_inputs_novos_vivo !== e.n_inputs_novos
                          ? `Inputs pendentes que este EGP traz para o mês, contados hoje: ${e.n_inputs_novos_vivo}. No plano congelado eram ${e.n_inputs_novos}, na unidade da época.`
                          : "Inputs pendentes que este EGP traz para o mês (input compartilhado conta no primeiro EGP que o traz)"}>
                        {e.n_inputs_novos_vivo ?? e.n_inputs_novos}
                      </div>
                      <div className="pe-cell num">{e.fan_out > 0 ? e.fan_out : "—"}</div>
                      <div className="pe-cell" title={e.responsavel ?? ""}>{nomeDe(e.responsavel)}</div>
                      <div className="pe-cell">
                        {isGestao && pode
                          ? <MoveControl cur={ep} nMeses={nMeses} busy={busy}
                              onMove={(mes) => setPin(e.projeto, mes)} />
                          : (ep != null ? "📌" : "")}
                      </div>
                    </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
        {!q.isFetching && meses.length === 0 && <div className="empty">Nenhum EGP no recorte atual.</div>}
      </div>
    </div>
  );
}

// Editor da capacidade (inputs/mês) — só gestão. Edição LOCAL (não salva): confirma no
// blur ou Enter (sem botão ✓); valor inválido volta ao atual. Aplica no Recalcular.
function CapControl({ cap, busy, onSave }: { cap: number; busy: boolean; onSave: (v: number) => void }) {
  const [val, setVal] = useState(String(cap));
  useEffect(() => setVal(String(cap)), [cap]);
  const commit = () => {
    const n = parseInt(val, 10);
    if (Number.isFinite(n) && n >= 1 && n <= 10000) { if (n !== cap) onSave(n); }
    else setVal(String(cap));  // inválido -> restaura
  };
  return (
    <span className="prio-cap" onClick={(ev) => ev.stopPropagation()}
      title="Capacidade de inputs/mês — edição local; aplica ao Recalcular (Enter ou sair do campo)">
      <input type="number" min={1} max={10000} value={val} disabled={busy}
        onChange={(ev) => setVal(ev.target.value)}
        onBlur={commit}
        onKeyDown={(ev) => { if (ev.key === "Enter") (ev.target as HTMLInputElement).blur(); }} />
    </span>
  );
}

// Seletor de mês por EGP (só gestão). "auto" = limpa o pin; "+ novo mês" = fixa em nMeses+1.
// `cur` é o pin EFETIVO (inclui edição local não salva). onMove só altera estado local.
function MoveControl({ cur, nMeses, busy, onMove }: {
  cur: number | null; nMeses: number; busy: boolean; onMove: (mes: number | null) => void;
}) {
  const months: number[] = [];
  for (let i = 1; i <= nMeses; i++) months.push(i);
  const newMonth = nMeses + 1;
  return (
    <div className="prio-move" onClick={(ev) => ev.stopPropagation()}>
      <select value={cur ?? ""} disabled={busy} title="Fixar este EGP num mês (📌)"
        onChange={(ev) => { const v = ev.target.value; onMove(v === "" ? null : Number(v)); }}>
        <option value="">auto</option>
        {months.map((i) => <option key={i} value={i}>Mês {i} — {calLabel(i)}</option>)}
        <option value={newMonth}>+ novo mês ({calLabel(newMonth)})</option>
      </select>
      {cur != null && (
        <button className="prio-clear" disabled={busy} title="Voltar ao automático"
          onClick={() => onMove(null)}>✕</button>
      )}
    </div>
  );
}
