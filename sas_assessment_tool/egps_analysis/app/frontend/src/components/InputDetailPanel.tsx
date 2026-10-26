import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { fmtTsBR } from "../diasUteis";
import { useState } from "react";
import type { Analista, InputRow, InputUsageEgp, PeriodoPar } from "../types";
import { PIPELINE_INPUT, STATUS_INPUT, SEG, confirmStatusTerminal } from "../pipeline";
import { effEtapa, effStatusInput, confirmEscritaFamilia, travaDerivada } from "../inputs";
import { GestaoStatusHistory } from "./GestaoStatusHistory";
import { mesTag, useMesPlan } from "../mesPlan";
import { PreworkingChecklist } from "./PreworkingChecklist";
import { pathFor, spaLinkClick } from "../routes";
import { usePodeEscrever } from "../usePodeEscrever";

const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
const isIndi = (v: string | boolean | null) => v === true || v === "true";

// Recorte do EGP consumidor/produtor (backend _enrich_egp_contexto). A pergunta que a lista
// "Usado por" responde é "quem AINDA depende disto" — e a resposta depende de duas coisas que
// antes não estavam na tela: o EGP está no nosso recorte? e em que pé está a migração dele?
// Ordem = prioridade de leitura (escopo primeiro, fora do escopo por último).
const ESCOPO: Record<string, { label: string; cls: string; ord: number; title: string }> = {
  indi:  { label: "escopo", ord: 0, cls: "esc-indi",
           title: "Escopo Indicium direto — este EGP é trabalho nosso e depende deste input." },
  dep:   { label: "dependência", ord: 1, cls: "esc-dep",
           title: "Dependência transitiva viva: entrou no recorte por ser upstream de um EGP do escopo Indicium." },
  ex:    { label: "ex-dependência", ord: 2, cls: "esc-ex",
           title: "Ex-dependência retida: já foi dependência e saiu do recorte vivo (cadeia despriorizada ou via resolvida)." },
  fora:  { label: "fora do escopo", ord: 3, cls: "esc-fora",
           title: "Fora do recorte (só aparece na base completa): consome o input, mas não é trabalho acompanhado — não deve pesar na decisão." },
};
const escOf = (e: InputUsageEgp) => ESCOPO[e.escopo ?? (isIndi(e.escopo_indi) ? "indi" : "fora")] ?? ESCOPO.fora;
// vínculo quebrado por último (não depende mais), depois recorte, depois nome.
const ordEgp = (a: InputUsageEgp, b: InputUsageEgp) =>
  Number(!!a.link_broken) - Number(!!b.link_broken)
  || escOf(a).ord - escOf(b).ord
  || a.projeto.localeCompare(b.projeto, "pt-BR");

// Link real para o deep-link do EGP (pathFor("readiness", ...)) em vez de <button>: o botão
// do meio, o ctrl/cmd+clique e o "abrir em nova guia" do menu de contexto passam a funcionar
// nativamente. O clique simples segue abrindo o EGP na mesma aba (SPA, sem reload).
function EgpLine({ e, mes, onOpen }: { e: InputUsageEgp; mes: string; onOpen: () => void }) {
  const esc = escOf(e);
  const st = e.status || "";
  return (
    <a className={`drawer-egp ${esc.cls}${e.link_broken ? " quebrado" : ""}`}
      href={pathFor("readiness", e.projeto)}
      title={`${e.projeto} — clique: abre o EGP · botão do meio/ctrl+clique: nova guia`}
      onClick={(ev) => spaLinkClick(ev, onOpen)}>
      <span className="de-name">
        {Number(e.ciclo_id) > 0 ? "⟳ " : ""}{shortName(e.projeto)}
        {e.link_broken && <span style={{ marginLeft: 4 }} title="Vínculo quebrado — este EGP declarou não depender deste input">⛓️‍💥</span>}
      </span>
      <span className="de-tags">
        <span className={`tag esc ${esc.cls}`} title={esc.title}>{esc.label}</span>
        <span className="de-etapa" title={`Etapa: ${e.etapa || "sem etapa definida"}`}>{e.etapa || "sem etapa"}</span>
        {st
          ? <span className="de-status" style={{ background: SEG[st]?.bg, color: SEG[st]?.fg }} title={`Status: ${st}`}>{st}</span>
          : <span className="de-status vazio" title="Sem status registrado no funil de migração">—</span>}
        <span className="de-meta">
          {e.area ?? "?"} · {mes}
          {e.n_safras ? ` · lê ${e.n_safras} safra${e.n_safras > 1 ? "s" : ""}` : ""}
        </span>
      </span>
    </a>
  );
}

// "desde 202401" / "últimos 12 meses" / "todas as safras" — o texto que a conversa de
// ingestão usa. `desde` é absoluto de propósito: relativo exige âncora, e é a âncora que
// travou a regra 12M/3M do cliente (ver ADR 0002).
function fmtProf(p: { tipo: string; valor?: string | null }): string {
  if (p.tipo === "todas") return "todas as safras";
  if (p.tipo === "rolling") return `últimos ${p.valor} meses`;
  if (p.tipo === "desde" && p.valor) return `desde ${p.valor.slice(0, 4)}-${p.valor.slice(4)}`;
  return "—";
}

// Editor da profundidade de UM par. "derivado" (opção vazia) apaga a declaração e o par
// volta a valer pelo corpus — o derivado nunca é gravado, então não há o que restaurar.
function PeriodoEditor({ par, disabled, onSave }: {
  par: PeriodoPar; disabled?: boolean; onSave: (tipo: string, valor: string | null) => void;
}) {
  const [tipo, setTipo] = useState(par.origem === "declarado" ? par.tipo : "");
  const [valor, setValor] = useState(par.valor ?? "");
  const precisaValor = tipo === "desde" || tipo === "rolling";
  return (
    <span className="de-etapa" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
      <select value={tipo} disabled={disabled}
        title="Vazio = usar o derivado do corpus (as safras que este EGP lê hoje)"
        onChange={(e) => {
          const t = e.target.value;
          setTipo(t);
          if (!t || t === "todas") onSave(t, null);
        }}>
        <option value="">derivado</option>
        <option value="todas">todas as safras</option>
        <option value="desde">desde AAAAMM</option>
        <option value="rolling">últimos N meses</option>
      </select>
      {precisaValor && (
        <input value={valor} disabled={disabled} size={7}
          placeholder={tipo === "desde" ? "202401" : "12"}
          title={tipo === "desde" ? "Safra mais antiga necessária (AAAAMM)" : "Número de meses"}
          onChange={(e) => setValor(e.target.value)}
          onBlur={() => { if (valor.trim()) onSave(tipo, valor.trim()); }} />
      )}
    </span>
  );
}

// Campo da profundidade INGERIDA. Aceita só AAAAMM (ou vazio, que apaga o registro) — a
// validação real está no backend; aqui é só evitar ida à rede com lixo digitado.
function IngeridaEditor({ atual, disabled, onSave }: {
  atual: string; disabled?: boolean; onSave: (v: string | null) => void;
}) {
  const [v, setV] = useState(atual);
  const invalido = !!v.trim() && !/^20\d{2}(0[1-9]|1[0-2])$/.test(v.trim());
  return (
    <>
      <input value={v} disabled={disabled} size={8} placeholder="AAAAMM"
        aria-invalid={invalido || undefined}
        title="Safra mais antiga que existe no destino (ex.: 202401). Vazio apaga o registro."
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          const t = v.trim();
          if (t === atual) return;
          if (t && invalido) { setV(atual); return; }
          onSave(t || null);
        }} />
      {invalido && <span className="muted" style={{ marginLeft: 4 }}>use AAAAMM</span>}
    </>
  );
}

interface Props {
  row: InputRow;
  onOpenEgp: (projeto: string) => void;
  // presentes quando aberto pela tabela de Inputs: habilitam a edição de
  // etapa/status/responsável aqui dentro (mesmo onPatch/opções das células da tabela)
  onPatch?: (chave: string, patch: Partial<InputRow>) => void;
  analistas?: Analista[];
}

// Detalhe de 1 input, renderizado dentro do DetailModal aberto pela tabela de Inputs
// (mesmo padrão da aba EGPs). Já foi drawer próprio (InputDrawer), depois expand inline
// (.rd-expand-detail); virou modal centrado em 2026-08-28 — no notebook o inline virava
// uma janela baixa com scroll aninhado. Título/✕/ESC vivem no DetailModal; aqui só o conteúdo.
export function InputDetailPanel({ row, onOpenEgp, onPatch, analistas }: Props) {
  const qc = useQueryClient();
  const { mesOf } = useMesPlan();
  const usage = useQuery({ queryKey: ["input", row.chave_canonica], queryFn: () => api.inputDetail(row.chave_canonica) });
  const cfgQ = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: 10 * 60 * 1000 });
  // Profundidade necessária: só a gestão declara (é pedido de ingestão ao BV, ver ADR 0002);
  // todos leem. Ao salvar, reinvalida o detalhe — o máximo da família pode mudar de dono.
  const ingMut = useMutation({
    mutationFn: (v: { desde: string | null }) =>
      api.familiaIngestao({ categoria: usage.data?.categoria ?? row.categoria,
                            familia: usage.data?.familia ?? row.artifact, desde: v.desde }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["input", row.chave_canonica] }),
  });
  const periodoMut = useMutation({
    mutationFn: (v: { projeto: string; tipo: string; valor?: string | null }) =>
      api.familiaPeriodo({ projeto: v.projeto, categoria: usage.data?.categoria ?? row.categoria,
                           familia: usage.data?.familia ?? row.artifact, tipo: v.tipo, valor: v.valor ?? null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["input", row.chave_canonica] }),
  });
  const audit = useQuery({ queryKey: ["audit", row.chave_canonica], queryFn: () => api.audit(row.chave_canonica) });

  const egps = usage.data?.egps ?? [];
  const produtores = usage.data?.produtores ?? [];
  // Safras da família (vazio quando a linha é um input físico): evidência read-only —
  // a edição é da família, não da safra (ADR 0002).
  const safras = usage.data?.safras ?? [];
  const pendentes = safras.filter((sf) => !sf.resolvido).length;
  const periodo = usage.data?.periodo;
  const isGestao = !!cfgQ.data?.is_gestao;
  const pode = usePodeEscrever();
  const hist =(audit.data?.rows ?? []).filter((h) => h.campo !== "create");
  const brokenCount = egps.filter((e) => e.link_broken).length;
  const activeCount = egps.length - brokenCount;
  // ordenados por recorte (escopo → dep → ex → fora) e, dentro dele, quebrados por último.
  const egpsOrd = [...egps].sort(ordEgp);
  const prodOrd = [...produtores].sort(ordEgp);
  // resumo do recorte só sobre os vínculos VIVOS — quebrado já não depende do input.
  const porEscopo = egpsOrd.reduce<Record<string, number>>((acc, e) => {
    if (!e.link_broken) acc[escOf(e).label] = (acc[escOf(e).label] ?? 0) + 1;
    return acc;
  }, {});
  const resumoEscopo = Object.entries(ESCOPO)
    .map(([, v]) => (porEscopo[v.label] ? `${porEscopo[v.label]} ${v.label}` : null))
    .filter(Boolean).join(" · ");

  return (
    <div className="input-detail">
      <div className="drawer-meta">
        <div><span className="k">Categoria</span><span>{row.categoria}</span></div>
        <div><span className="k">Origem</span><span title={row.source_types}>{row.source_types || "—"}</span></div>
        <div><span className="k">Áreas</span><span title={row.areas}>{row.areas || "—"}</span></div>
        <div><span className="k">Projetos</span><span>{row.qtd_projetos}</span></div>
        <div><span className="k">Auto</span><span className={`pill ${row.modernizada_auto === "Disponível" ? "ok" : "todo"}`}>{row.modernizada_auto === "Disponível" ? "BQ" : "ingerir"}</span></div>
        <div><span className="k">Etapa</span><span>
          {onPatch ? (
            <select value={effEtapa(row.etapa, row.modernizada_auto)}
              disabled={!!travaDerivada(row)} title={travaDerivada(row)}
              onChange={(e) => { const v = e.target.value;
                if (!confirmEscritaFamilia(row, "etapa")) return;
                onPatch(row.chave_canonica, { etapa: v }); }}>
              {PIPELINE_INPUT.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          ) : (row.etapa || "—")}
        </span></div>
        <div><span className="k">Status</span><span>
          {onPatch ? (() => {
            const effSt = effStatusInput(row.status, row.etapa, row.modernizada_auto);
            return (
              <select value={effSt} style={{ background: SEG[effSt]?.bg, color: SEG[effSt]?.fg }}
                disabled={!!travaDerivada(row)} title={travaDerivada(row)}
                onChange={(e) => { const v = e.target.value;
                  if (!confirmStatusTerminal(v, row.artifact)) return;
                  if (!confirmEscritaFamilia(row, `status "${v}"`)) return;
                  onPatch(row.chave_canonica, { status: v }); }}>
                {STATUS_INPUT.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            );
          })() : (row.status || "—")}
        </span></div>
        <div><span className="k">Responsável</span><span>
          {onPatch && analistas ? (
            <select value={row.responsavel ?? ""} title="Responsável pela ingestão deste input"
              onChange={(e) => onPatch(row.chave_canonica, { responsavel: e.target.value })}>
              <option value="">—</option>
              {row.responsavel && !analistas.some((a) => a.email === row.responsavel) && (
                <option value={row.responsavel}>{row.responsavel}</option>
              )}
              {analistas.map((a) => <option key={a.email} value={a.email}>{a.nome || a.email}</option>)}
            </select>
          ) : (row.responsavel || "—")}
        </span></div>
      </div>

      {row.sanitizado_derivado && (
        <p className="muted" title="Estado DERIVADO: nada foi gravado. Etapa e status reais continuam no banco e reaparecem sozinhos quando a condição deixa de valer — o consumidor é repriorizado, ou o vínculo com a versão nova é desfeito.">
          🚫 <b>Sanitizado por derivação</b> — {row.sanitizado_motivo}. Não é pedido de
          ingestão ao BV, por isso aparece como Modernizado + Sanitizado e etapa/status não se
          editam; o gravado continua <b>{row.etapa_real || "vazio"}</b> / <b>{row.status_real || "vazio"}</b>.
        </p>
      )}

      <PreworkingChecklist chave={row.chave_canonica} onAutoAvancado={() => {
        // 100% -> o backend já avançou etapa/status p/ "Ingestão UAT"/"A Iniciar" em
        // sas_inputs_monitor: invalida o que depende disso (a linha da tabela acima fica
        // com a etapa/status do momento em que expandiu).
        qc.invalidateQueries({ queryKey: ["inputs"] });
        qc.invalidateQueries({ queryKey: ["audit", row.chave_canonica] });
        qc.invalidateQueries({ queryKey: ["metrics"] });
        qc.invalidateQueries({ queryKey: ["resumo"] });
        qc.invalidateQueries({ queryKey: ["landing"] });
        qc.invalidateQueries({ queryKey: ["egp"] });
        qc.invalidateQueries({ queryKey: ["egp-readiness"] });
        qc.invalidateQueries({ queryKey: ["funis"] });
      }} />

      {safras.length > 0 && (
        <>
          <h4>
            {safras.length} safras desta família
            <span className="muted h4-sub" title="A família é a unidade de input: a ingestão dela é UMA tabela particionada no destino. As safras abaixo são evidência — quem lê o quê e o que já foi resolvido —, não unidades de trabalho.">
              {pendentes > 0 ? `${pendentes} pendente${pendentes > 1 ? "s" : ""}` : "todas resolvidas"}
              {row.safra_min ? ` · ${row.safra_min}–${row.safra_max}` : ""}
            </span>
          </h4>
          <div className="drawer-egps">
            {safras.map((sf) => (
              <div key={sf.chave_canonica} className={`drawer-egp${sf.resolvido ? " quebrado" : ""}`}
                style={{ cursor: "default" }}
                title={`${sf.artifact}${sf.responsavel ? ` · ${sf.responsavel}` : ""}${sf.observacao ? ` · ${sf.observacao}` : ""}`}>
                <span className="de-name">
                  {sf.resolvido ? "✔ " : ""}{sf.artifact}
                  {!sf.etapa && !sf.status && (
                    <span className="muted" style={{ marginLeft: 6 }} title="Nenhuma edição humana nesta safra: estado derivado da detecção automática.">auto</span>
                  )}
                </span>
                <span className="de-tags">
                  <span className="de-etapa" title={`Etapa efetiva: ${sf.etapa_efetiva}`}>{sf.etapa_efetiva}</span>
                  <span className="de-status" style={{ background: SEG[sf.status_efetivo]?.bg, color: SEG[sf.status_efetivo]?.fg }}
                    title={`Status efetivo: ${sf.status_efetivo}`}>{sf.status_efetivo}</span>
                  <span className="de-meta">{sf.modernizada_auto === "Disponível" ? "BQ" : "a ingerir"}</span>
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {periodo && periodo.pares.length > 0 && (
        <>
          <h4>
            Profundidade necessária
            <span className="muted h4-sub" title="Até que ponto do passado cada EGP precisa desta família. É propriedade do PAR (EGP × família): consumidores da mesma família pedem profundidades diferentes. O valor nasce DERIVADO das safras que o EGP lê hoje; a gestão pode declarar outro.">
              {periodo.maximo
                ? `a ingerir: ${fmtProf(periodo.maximo)} · pedida por ${shortName(periodo.maximo_projeto ?? "")}`
                : (periodo.maximo_motivo ?? "sem máximo definido")}
              {periodo.n_esparsos > 0 ? ` · ${periodo.n_esparsos} com leitura esparsa` : ""}
            </span>
          </h4>
          <div className="drawer-meta" style={{ marginBottom: 6 }}>
            <div>
              <span className="k" title="A safra mais antiga que de fato existe no destino depois da carga. Fato consumado — quem subiu os arquivos registra (qualquer analista). Vazio é estado normal: sem registro, não há aviso de carga rasa, só a dispersão do que os consumidores pedem.">
                Ingerida desde
              </span>
              <span>
                <IngeridaEditor atual={periodo.ingerida?.desde ?? ""} disabled={ingMut.isPending || !pode}
                  onSave={(v) => ingMut.mutate({ desde: v })} />
                {periodo.ingerida?.ingerida_em && (
                  <span className="muted" style={{ marginLeft: 6 }}>
                    carga em {periodo.ingerida.ingerida_em}
                  </span>
                )}
              </span>
            </div>
          </div>
          {periodo.avisos?.rasa && (
            <p className="muted" title="A carga alcança menos passado do que estes consumidores precisam. É AVISO, não bloqueio: o EGP não fica travado por isto.">
              ⚠ <b>Carga rasa</b> para {periodo.avisos.rasa.n} de {periodo.avisos.rasa.de}{" "}
              consumidor{periodo.avisos.rasa.de === 1 ? "" : "es"} vivo{periodo.avisos.rasa.de === 1 ? "" : "s"}:
              o mais fundo é <b>{shortName(periodo.avisos.rasa.mais_fundo)}</b>, que precisa de{" "}
              {periodo.avisos.rasa.precisa}.
            </p>
          )}
          {!periodo.ingerida?.desde && periodo.avisos?.dispersao && (
            <p className="muted" title="Faixa do que os consumidores vivos pedem. É o número que decide a carga: dá para subir o mínimo e destravar parte deles, sem carregar o histórico inteiro por causa de um só.">
              Consumidores pedem de <b>{periodo.avisos.dispersao.min_meses}</b> a{" "}
              <b>{periodo.avisos.dispersao.max_meses}</b> meses de passado
              {periodo.avisos.dispersao.max_meses !== periodo.avisos.dispersao.min_meses
                ? ` (o mais fundo é ${shortName(periodo.avisos.dispersao.mais_fundo)})`
                : ""}.
            </p>
          )}
          {(periodo.avisos?.esparsos?.length ?? 0) > 0 && (
            <p className="muted" title="Leitura esparsa: o EGP lê safras com buracos no intervalo (ex.: só dezembros). A profundidade continua sendo a safra mais antiga, mas carregar o intervalo inteiro entrega muito mais do que ele usa.">
              {periodo.avisos!.esparsos!.length} consumidor{periodo.avisos!.esparsos!.length === 1 ? "" : "es"}{" "}
              com <b>leitura esparsa</b> — carregar o intervalo inteiro entrega mais do que eles usam.
            </p>
          )}
          <div className="drawer-egps">
            {periodo.pares.map((p) => (
              <div key={p.projeto} className="drawer-egp" style={{ cursor: "default" }}
                title={`${p.projeto}${p.origem === "declarado" ? ` · derivado do corpus seria ${p.derivado_tipo ?? "?"} ${p.derivado_valor ?? ""}` : ""}`}>
                <span className="de-name">
                  {p.projeto === periodo.maximo_projeto ? "▲ " : ""}{shortName(p.projeto)}
                </span>
                <span className="de-tags">
                  {isGestao && pode ? (
                    <PeriodoEditor par={p} disabled={periodoMut.isPending}
                      onSave={(tipo, valor) => periodoMut.mutate({ projeto: p.projeto, tipo, valor })} />
                  ) : (
                    <span className="de-etapa">{fmtProf(p)}</span>
                  )}
                  <span className={`tag ${p.origem === "declarado" ? "esc-indi" : "esc-fora"}`}
                    title={p.origem === "declarado"
                      ? "Declarado pela gestão — vence o derivado e sobrevive a refresh/publish."
                      : "Derivado das safras que este EGP lê hoje; recalculado a cada leitura."}>
                    {p.origem}
                  </span>
                  <span className="de-meta">
                    lê {p.n_safras_lidas ?? 0} safra{(p.n_safras_lidas ?? 0) === 1 ? "" : "s"}
                    {p.span_meses ? ` em ${p.span_meses}m` : ""}
                    {p.esparso && (
                      <span title="Leitura ESPARSA: lê safras com buracos no intervalo (ex.: só dezembros). A profundidade continua sendo a safra mais antiga, mas carregar o intervalo inteiro entrega muito mais do que este EGP usa."> · esparsa</span>
                    )}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      <h4>Produzido por {produtores.length} EGP{produtores.length === 1 ? "" : "s"}</h4>
      {usage.isFetching && <div className="muted">carregando…</div>}
      <div className="drawer-egps">
        {prodOrd.map((e) => (
          <EgpLine key={e.projeto} e={e} mes={mesTag(mesOf.get(e.projeto))}
            onOpen={() => onOpenEgp(e.projeto)} />
        ))}
        {!usage.isFetching && produtores.length === 0 && <div className="muted">— origem externa (nenhum EGP do corpus produz)</div>}
      </div>

      <h4>
        Usado por {usage.isFetching && egps.length === 0 ? row.qtd_projetos : activeCount} EGP{activeCount === 1 ? "" : "s"}
        {resumoEscopo && (
          <span className="muted h4-sub" title="Quebra por recorte dos vínculos vivos: quem está no escopo Indicium, quem entrou como dependência e quem está fora do recorte acompanhado.">
            {resumoEscopo}
          </span>
        )}
        {brokenCount > 0 && <span className="muted h4-sub">+ {brokenCount} com vínculo quebrado</span>}
      </h4>
      {usage.isFetching && <div className="muted">carregando…</div>}
      {usage.error && <div className="error">{String(usage.error)}</div>}
      <div className="drawer-egps">
        {egpsOrd.map((e) => (
          <EgpLine key={e.projeto} e={e} mes={mesTag(mesOf.get(e.projeto))}
            onOpen={() => onOpenEgp(e.projeto)} />
        ))}
        {!usage.isFetching && egps.length === 0 && <div className="muted">— nenhum EGP encontrado</div>}
      </div>

      <h4>Histórico de alterações</h4>
      {audit.isFetching && <div className="muted">carregando…</div>}
      <div className="drawer-audit">
        {hist.map((h, i) => (
          <div key={i} className="da-row">
            <span className="da-campo">{h.campo}</span>
            <span className="da-val">
              {h.valor_antigo || "—"} → <b>{h.valor_novo || "—"}</b>
              {/* fan-out da família: o backend já devolve UMA linha por edição, com
                  quantas safras ela tocou — sem isso eram N linhas idênticas aqui */}
              {(h.n_safras ?? 1) > 1 && <span className="muted"> · {h.n_safras} cargas</span>}
            </span>
            <span className="da-who">{h.updated_by || "?"} · {fmtTsBR(h.updated_at, false)}</span>
          </div>
        ))}
        {!audit.isFetching && hist.length === 0 && <div className="muted">— sem alterações registradas</div>}
      </div>

      <h4>Último status &amp; histórico (Gestão)</h4>
      <GestaoStatusHistory entity="input" id={row.chave_canonica} />
    </div>
  );
}
