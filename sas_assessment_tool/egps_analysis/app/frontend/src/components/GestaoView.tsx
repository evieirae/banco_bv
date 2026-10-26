import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { GestaoMigracao } from "./GestaoMigracao";
import type { Analista, EgpNovoRow, ResponsavelBv } from "../types";
import { PAPEIS } from "../organograma";
import { useSubareas } from "../useSubareas";
import { usePodeEscrever } from "../usePodeEscrever";

const isAtivo = (v: boolean | string) => v === true || v === "true";

/** Célula de sub-área do responsável BV.
 *
 * Controlada de propósito. Era um `<input defaultValue={b.subarea}>` dentro de um `<tr>`
 * de `key` estável: depois de um refetch (toda mutação invalida a lista) o React mantinha
 * o texto de quando o input montou, mas o `onBlur` comparava com o valor FRESCO do
 * servidor. Resultado: bastava tabular pelo campo, sem digitar nada, para regravar o
 * valor velho por cima do que outra pessoa — ou o `scripts/normaliza_responsavel_bv.py` —
 * tinha acabado de mudar, reclassificando todos os EGPs daquele responsável.
 *
 * Adota valor novo do servidor apenas quando não há edição pendente aqui, para um refetch
 * disparado pela edição de OUTRA linha não apagar o que está sendo digitado nesta. */
function CelulaSubarea({ valor, onSalvar, disabled }: { valor: string; onSalvar: (v: string) => void; disabled?: boolean }) {
  const [texto, setTexto] = useState(valor);
  const [visto, setVisto] = useState(valor);
  if (valor !== visto) {
    setVisto(valor);
    if (texto === visto) setTexto(valor);   // só adota se o usuário não mexeu
  }
  return (
    <input value={texto} list="subareas-bv" placeholder="—" disabled={disabled}
      title="Área interna do BV desta pessoa"
      onChange={(e) => setTexto(e.target.value)}
      onBlur={() => { const v = texto.trim(); if (v !== valor) onSalvar(v); }} />
  );
}

// Aba Gestão: gerencia a lista de analistas (fonte dos dropdowns de responsável). Restrita a
// bv_users — o App já esconde a aba de quem não é do grupo; o backend reforça (403) nas escritas.
export function GestaoView() {
  const qc = useQueryClient();
  const pode = usePodeEscrever();
  // inclui inativos: gestores precisam ver/reativar quem foi desativado (dropdowns só veem ativos)
  const q = useQuery({ queryKey: ["analistas", "all"], queryFn: () => api.analistas(true) });
  const [email, setEmail] = useState("");
  const [nome, setNome] = useState("");
  const [papel, setPapel] = useState("");
  const [organograma, setOrganograma] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // Cadastro Responsável BV -> sub-área (mesma estrutura do cadastro de analistas abaixo).
  // Inclui inativos: gestores precisam ver/reativar quem foi desativado.
  const qBv = useQuery({ queryKey: ["responsaveis-bv", "all"], queryFn: () => api.responsaveisBv(true) });
  const { subareas: subareasCadastradas } = useSubareas();
  const [bvNome, setBvNome] = useState("");
  const [bvSub, setBvSub] = useState("");

  const upsertBv = useMutation({
    mutationFn: (b: { nome: string; subarea?: string; ativo?: boolean }) => api.responsavelBvUpsert(b),
    // invalida as DUAS chaves: a lista desta tela ("all") e a que alimenta o filtro de
    // sub-área nas outras abas (["responsaveis-bv"]).
    onSuccess: () => qc.invalidateQueries({ queryKey: ["responsaveis-bv"] }),
    onError: (e) => setMsg(`Falha: ${e}`),
  });

  const bvRows: ResponsavelBv[] = qBv.data?.rows ?? [];

  // EGPs declarados NOVOS (ticket 24) — a 3ª perna do `extra`. As outras duas saem do
  // vínculo e do publish; esta era a única que só existia como linha escrita por script.
  const qNovos = useQuery({ queryKey: ["egps-novos"], queryFn: () => api.egpsNovos() });
  // Mesma queryKey do VinculoSucessorPanel (cache compartilhado): o universo é o CORPUS, e é a
  // mesma lista que a guarda 404 do servidor consulta (sas_lineage_nodes).
  const nodesQ = useQuery({ queryKey: ["nodes-all"], queryFn: () => api.lineageSearch("", "", "", 5000) });
  const projetosCorpus = useMemo(
    () => (nodesQ.data?.rows ?? []).map((n) => n.projeto).filter(Boolean).sort(),
    [nodesQ.data]);
  const [novoProj, setNovoProj] = useState("");

  const patchNovo = useMutation({
    mutationFn: (b: { projeto: string; acao: "declarar" | "remover" }) => api.egpNovoPatch(b),
    onSuccess: (r) => {
      setMsg(r.acao === "declarar"
        ? `"${r.projeto}" declarado como novo — passa a contar no "(+N extra)".`
        : `"${r.projeto}" não é mais declarado novo.`);
      setNovoProj("");
      // a declaração muda quem é extra: o contador, a aba EGPs e o Resumo leem isso.
      qc.invalidateQueries({ queryKey: ["egps-novos"] });
      // sobre-invalidar só custa um re-query; sob-invalidar deixa número velho na tela.
      for (const k of ["egp-readiness", "landing", "resumo", "funis"]) {
        qc.invalidateQueries({ queryKey: [k] });
      }
    },
    // o detail da recusa é a informação ÚTIL (404 fora do corpus, 409 na linha de base ou
    // já extra por vínculo) — engolir isso devolveria "falhou" sem dizer o que fazer.
    onError: (e) => setMsg(`Falha: ${e}`),
  });

  const novosRows: EgpNovoRow[] = qNovos.data?.rows ?? [];

  function addNovo() {
    const n = novoProj.trim();
    if (!n) { setMsg("Informe o projeto do corpus."); return; }
    setMsg(null);
    patchNovo.mutate({ projeto: n, acao: "declarar" });
  }

  function addBv() {
    const n = bvNome.trim();
    if (!n) { setMsg("Informe o nome do responsável BV."); return; }
    // subarea vazia vira undefined (campo ausente no upsert PARCIAL do backend): digitar um
    // nome JÁ cadastrado no formulário de adicionar, com a caixa de sub-área vazia, apagaria
    // a sub-área dele. Na tabela abaixo o "" é mantido de propósito — lá apagar é a intenção.
    upsertBv.mutate({ nome: n, subarea: bvSub.trim() || undefined, ativo: true });
    setBvNome(""); setBvSub(""); setMsg(null);
  }

  const invalidate = () => qc.invalidateQueries({ queryKey: ["analistas"] });

  const upsert = useMutation({
    mutationFn: (b: { email: string; nome?: string; ativo?: boolean; papel?: string; organograma?: boolean }) => api.analistaUpsert(b),
    onSuccess: invalidate,
    onError: (e) => setMsg(`Falha: ${e}`),
  });
  const rows: Analista[] = q.data?.rows ?? [];

  function add() {
    const e = email.trim().toLowerCase();
    if (!e.includes("@")) { setMsg("Informe um email válido."); return; }
    upsert.mutate({ email: e, nome: nome.trim() || undefined, ativo: true,
      papel: papel || undefined, organograma });
    setEmail(""); setNome(""); setPapel(""); setOrganograma(false); setMsg(null);
  }

  return (
    <div className="resumo">
      {/* Gestão de EGPs/Inputs (switch interno) — dados reais via /api/gestao/* (gestaoApi.ts) */}
      <GestaoMigracao />

      <h3>EGPs novos</h3>
      <p className="muted">
        EGP que entrou no escopo <b>depois do congelamento</b> e <b>não substitui ninguém</b> —
        nenhum vínculo o alcança. É a 3ª perna do <b>extra</b>: as outras duas (<b>sucessor</b> e
        <b>casca</b>) são derivadas do vínculo e do publish, esta é declarada aqui.
        Declarar <b>não mexe no total congelado</b>; só soma no contador <b>(+N extra)</b> ao lado dele.
      </p>

      {pode && (
        <div className="rsm-card">
          <div className="gestao-add">
            <input type="text" list="corpus-egps-novos" placeholder="projeto do corpus (Área__Nome)"
              value={novoProj} onChange={(e) => setNovoProj(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addNovo(); }} />
            <datalist id="corpus-egps-novos">
              {projetosCorpus.map((p) => <option key={p} value={p} />)}
            </datalist>
            <button className="theme-btn" onClick={addNovo} disabled={patchNovo.isPending}>+ Declarar</button>
          </div>
        </div>
      )}

      {qNovos.error && <div className="error">{String(qNovos.error)}</div>}
      <div className="rsm-card">
        <table className="rsm-tbl">
          <thead>
            <tr><th>Projeto</th><th>Por que é extra hoje</th><th style={{ width: 90 }}></th></tr>
          </thead>
          <tbody>
            {novosRows.map((n) => (
              <tr key={n.projeto} className={n.redundante ? "zero" : undefined}>
                <td>{n.projeto}</td>
                <td>
                  {/* o motivo que sobraria SEM a declaração: quando deixa de ser vazio, a
                      linha virou letra morta e a lista está guardando lixo. */}
                  {n.redundante
                    ? <span title="O EGP ganhou vínculo depois: ele já seria extra sem esta declaração, que agora não faz efeito. Pode remover.">
                        já é <b>{n.motivo_sem_declaracao}</b> por vínculo — declaração redundante
                      </span>
                    : !n.no_corpus
                      ? <span title="O projeto saiu do corpus (ou ainda não entrou). A declaração não produz extra nenhum enquanto isso.">
                          fora do corpus
                        </span>
                      : <span>declarado novo</span>}
                </td>
                <td>
                  {pode && (
                    <button className="theme-btn" disabled={patchNovo.isPending}
                      onClick={() => patchNovo.mutate({ projeto: n.projeto, acao: "remover" })}>
                      Remover
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {novosRows.length === 0 && (
              <tr><td colSpan={3} className="muted">Nenhum EGP declarado novo.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <h3>Responsáveis BV</h3>
      <p className="muted">
        A <b>sub-área BV</b> é a área interna do cliente (Digital, MIS, Operações,
        Estratégia - cartões/rodas, Riscos) e vale por <b>pessoa</b>: cadastrar alguém aqui
        reclassifica todos os EGPs em que ela é Responsável BV. Quem não estiver nesta lista
        aparece como <b>Sem sub-área</b> nas demais abas.
      </p>

      {pode && (
        <div className="rsm-card">
          <div className="gestao-add">
            <input type="text" placeholder="nome (como está no EGP)" value={bvNome}
              onChange={(e) => setBvNome(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") addBv(); }} />
            <input type="text" list="subareas-bv" placeholder="sub-área" value={bvSub}
              onChange={(e) => setBvSub(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") addBv(); }} />
            <datalist id="subareas-bv">
              {subareasCadastradas.map((s) => <option key={s} value={s} />)}
            </datalist>
            <button className="theme-btn" onClick={addBv} disabled={upsertBv.isPending}>+ Adicionar</button>
          </div>
        </div>
      )}

      {qBv.error && <div className="error">{String(qBv.error)}</div>}
      <div className="rsm-card">
        <table className="rsm-tbl">
          <thead>
            <tr><th>Nome</th><th>Sub-área</th><th style={{ width: 70 }}>Ativo</th></tr>
          </thead>
          <tbody>
            {bvRows.map((b) => (
              <tr key={b.nome_key} className={isAtivo(b.ativo) ? undefined : "zero"}>
                <td>{b.nome}</td>
                <td>
                  <CelulaSubarea valor={b.subarea ?? ""} disabled={!pode}
                    onSalvar={(v) => upsertBv.mutate({ nome: b.nome, subarea: v })} />
                </td>
                <td>
                  <input type="checkbox" checked={isAtivo(b.ativo)} disabled={!pode}
                    title={isAtivo(b.ativo) ? "Ativo — desmarque para desativar" : "Inativo — marque para reativar"}
                    onChange={(e) => upsertBv.mutate({ nome: b.nome, ativo: e.target.checked })} />
                </td>
              </tr>
            ))}
            {!qBv.isFetching && bvRows.length === 0 && (
              <tr><td colSpan={3} className="muted">Nenhum responsável BV cadastrado.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <h3>Gestão de analistas</h3>
      <p className="muted">
        Analistas disponíveis nos dropdowns de responsável (EGPs = migração, inputs = ingestão).
        Aba restrita ao grupo <b>bv_users</b>.
      </p>

      {pode && (
        <div className="rsm-card">
          <div className="gestao-add">
            <input type="email" placeholder="email@indicium.tech" value={email}
              onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
            <input type="text" placeholder="nome (opcional)" value={nome}
              onChange={(e) => setNome(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
            <select value={papel} onChange={(e) => setPapel(e.target.value)} title="Cargo (define a coluna no organograma da Home)">
              <option value="">papel (organograma)…</option>
              {PAPEIS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <label className="chk" title="Exibir esta pessoa no organograma da aba Home">
              <input type="checkbox" checked={organograma} onChange={(e) => setOrganograma(e.target.checked)} />
              organograma
            </label>
            <button className="theme-btn" onClick={add} disabled={upsert.isPending}>+ Adicionar</button>
          </div>
          {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
        </div>
      )}

      {q.error && <div className="error">{String(q.error)}</div>}
      <div className="rsm-card">
        <table className="rsm-tbl">
          <thead>
            <tr><th>Nome</th><th>Email</th><th>Papel</th><th style={{ width: 90 }}>Organograma</th><th style={{ width: 70 }}>Ativo</th></tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.email} className={isAtivo(a.ativo) ? undefined : "zero"}>
                <td>
                  <input defaultValue={a.nome ?? ""} placeholder="—" disabled={!pode}
                    onBlur={(e) => { const v = e.target.value.trim(); if (v !== (a.nome ?? "")) upsert.mutate({ email: a.email, nome: v }); }} />
                </td>
                <td>{a.email}</td>
                <td>
                  <select value={a.papel ?? ""} title="Cargo (define a coluna no organograma)" disabled={!pode}
                    onChange={(e) => upsert.mutate({ email: a.email, papel: e.target.value })}>
                    <option value="">—</option>
                    {PAPEIS.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                </td>
                <td>
                  <input type="checkbox" checked={!!a.organograma} disabled={!pode}
                    title="Exibir no organograma da aba Home"
                    onChange={(e) => upsert.mutate({ email: a.email, organograma: e.target.checked })} />
                </td>
                <td>
                  <input type="checkbox" checked={isAtivo(a.ativo)} disabled={!pode}
                    title={isAtivo(a.ativo) ? "Ativo — desmarque para desativar" : "Inativo — marque para reativar"}
                    onChange={(e) => upsert.mutate({ email: a.email, ativo: e.target.checked })} />
                </td>
              </tr>
            ))}
            {!q.isFetching && rows.length === 0 && (
              <tr><td colSpan={5} className="muted">Nenhum analista cadastrado. Adicione acima.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
