import { useEffect, useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { ReadinessRow } from "../types";
import { pathFor, spaLinkClick } from "../routes";
import { TIPOS_VINCULO, TIPO_AJUDA, TIPO_SUBSTITUIDO, mensagemErroVinculo,
  sucessoresCandidatos, sucessorSugerido, vinculoCompleto } from "../vinculo";

// A IGNIÇÃO do vínculo antecessor -> sucessor (ticket 20, 29/09/2026). O motor existe
// desde o ticket 03 — colunas, guardas, derivação, funil — e não havia como ligá-lo pela
// tela: o único botão de vínculo era o `AtualizadoLinkButton`, que grava OUTRA coluna.
//
// As duas colunas, que é a confusão que originou o ticket:
//   egp_atualizado_key  -> chave da ABA de recebimentos (`Área__nome`). Serve para achar a
//                          COMPARAÇÃO antigo x novo. Não muda status, etapa nem contagem.
//   egp_vinculo_tipo    -> o VÍNCULO de verdade. Aponta para o PROJETO do corpus
//   + egp_sucessor         (`Área__nome__ATU<data>`) e é o único que deriva `Desatualizado`,
//                          espelha a etapa e sanitiza os inputs exclusivos.
// As duas continuam existindo porque descrevem fatos diferentes (spec §5, "o que fica").
//
// Regras que este componente NÃO decide (são do backend, app/backend/vinculos.py): o status
// exibido, a etapa espelhada, a cópia de etapa/mês/JIRA/responsável para o sucessor e as 4
// guardas. Aqui só se escolhe tipo + sucessor, se desfaz, e se mostra o erro que voltar.

const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);

export function VinculoSucessorPanel({ projeto, row, isGestao, onOpenEgp }: {
  projeto: string;
  row?: ReadinessRow | null;
  isGestao: boolean;
  onOpenEgp?: (projeto: string) => void;
}) {
  const qc = useQueryClient();
  const listId = useId();
  // Mesmo queryKey do Indicium/Linhagem (cache compartilhado entre as abas): o universo do
  // sucessor é o CORPUS inteiro (~1.260 projetos), não o recorte da aba — o sucessor
  // acabou de entrar e pode estar fora do escopo. É a mesma lista que a guarda 404 do
  // servidor consulta (sas_lineage_nodes).
  const tipoAtual = row?.vinculo_tipo ?? null;
  const sucessorAtual = row?.sucessor ?? null;
  const vinculado = !!(tipoAtual && sucessorAtual);
  // Só o formulário de criar vínculo usa a lista (gestão + ainda sem vínculo): fora dele,
  // abrir um EGP buscava 5.000 nós à toa — o prefetch deixou de aquecer esta chave (2026-10).
  const nodesQ = useQuery({ queryKey: ["nodes-all"], queryFn: () => api.lineageSearch("", "", "", 5000),
    enabled: isGestao && !vinculado });
  const projetos = useMemo(
    () => (nodesQ.data?.rows ?? []).map((n) => n.projeto).filter(Boolean).sort(),
    [nodesQ.data]);

  // Pré-preenchimento: o `egp_atualizado_key` já foi confirmado por um humano e, quando a
  // versão dele entrou no corpus, a chave do projeto é `<aquela chave>__ATU<data>`. Sugerir
  // o sucessor poupa a busca entre ~1.260 projetos sem inventar nada — o TIPO segue em
  // branco de propósito (não é derivável, spec §1). Editável: é sugestão, não decisão.
  const sugestao = useMemo(
    () => sucessorSugerido(row?.egp_atualizado_key, projetos), [row?.egp_atualizado_key, projetos]);
  const candidatos = useMemo(
    () => sucessoresCandidatos(row?.egp_atualizado_key, projetos), [row?.egp_atualizado_key, projetos]);

  const [tipo, setTipo] = useState("");
  const [sucessor, setSucessor] = useState("");
  useEffect(() => { setSucessor(sugestao ?? ""); }, [sugestao]);

  const mut = useMutation({
    mutationFn: (v: { egp_vinculo_tipo: string; egp_sucessor: string }) =>
      api.egpPipeline({ projeto, ...v }),
    onSuccess: () => {
      // O vínculo muda status exibido, etapa espelhada, denominador de extras, funis e a
      // linha do SUCESSOR (cópia do §3.3.11) — invalida tudo que lê alguma dessas coisas.
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      // prefixo "egp": invalida o detalhe deste E o do SUCESSOR, que acabou de receber a
      // cópia de etapa/mês/JIRA/responsável (§3.3.11). Não colide com ["egp-readiness"].
      qc.invalidateQueries({ queryKey: ["egp"] });
      qc.invalidateQueries({ queryKey: ["funis"] });
      qc.invalidateQueries({ queryKey: ["resumo"] });
      qc.invalidateQueries({ queryKey: ["landing"] });
      qc.invalidateQueries({ queryKey: ["egps-extras"] });
      qc.invalidateQueries({ queryKey: ["scope-egps"] });
      qc.invalidateQueries({ queryKey: ["priorizacao"] });
      qc.invalidateQueries({ queryKey: ["gestao", "egp"] });
    },
  });

  const desfazer = () => {
    // "" limpa as duas colunas (o PATCH trata "" como NULL). Desfazer DEVOLVE o status
    // real: nada foi gravado, o `Desatualizado` era derivado (spec §3.2.6).
    if (!window.confirm(
      `Desfazer o vínculo de "${shortName(projeto)}" com "${shortName(sucessorAtual ?? "")}"?\n\n`
      + "O status real volta a aparecer (nada foi gravado por cima) e a etapa volta a ser "
      + "editável aqui. O trabalho já copiado para o sucessor fica lá.")) return;
    mut.mutate({ egp_vinculo_tipo: "", egp_sucessor: "" });
  };

  const erro = mut.isError ? mensagemErroVinculo(mut.error) : null;

  // O vínculo é gravado no ANTECESSOR e aponta para frente, então abrir o EGP atualizado
  // não dizia o que ele substitui — era preciso adivinhar pelo nome ou achar o antecessor
  // na lista. A lista vem pronta do backend (`antecessores_por_sucessor`), inclusive com
  // antecessor fora do recorte, que é justamente o caso da casca.
  const antecessores = row?.antecessores ?? [];

  const linkEgp = (p: string) => (onOpenEgp
    ? <a className="rd-egp-link" href={pathFor("readiness", p)}
        title={`${p} — clique: abre o EGP · ctrl+clique: nova guia`}
        onClick={(ev) => spaLinkClick(ev, () => onOpenEgp(p))}>{shortName(p)}</a>
    : <b title={p}>{shortName(p)}</b>);

  return (
    <div className="vinc-box">
      {antecessores.length > 0 && (
        <div className="vinc-antec">
          <b>Substitui {antecessores.length === 1 ? "o EGP" : `${antecessores.length} EGPs`}</b>
          <ul>
            {antecessores.map((a) => (
              <li key={a.projeto}>
                {linkEgp(a.projeto)}
                {a.tipo && <> · <span className="muted">{a.tipo}</span></>}
              </li>
            ))}
          </ul>
          <div className="muted">
            {antecessores.length === 1 ? "Este antecessor exibe" : "Estes antecessores exibem"}{" "}
            <b>Desatualizado</b> por causa deste EGP. Desfazer o vínculo se faz na linha
            {antecessores.length === 1 ? " dele" : " de cada um"}.
          </div>
        </div>
      )}

      <div className="vinc-explica">
        <b>Vínculo com o sucessor</b> — aponta para o <b>projeto do corpus</b> que substitui
        este EGP. É ele que faz o antecessor exibir <b>Desatualizado</b>, espelhar a etapa do
        sucessor e sanitizar os inputs que só ele lia. O sucessor precisa já ter entrado no
        corpus (extrator → orquestrador → publish); antes disso o servidor recusa.
      </div>

      {vinculado ? (
        <div className="vinc-atual">
          <span>
            Vinculado como <b>{tipoAtual}</b> →{" "}
            {linkEgp(sucessorAtual!)}
            {" "}· <span className="muted">{TIPO_AJUDA[tipoAtual!] ?? ""}</span>
          </span>
          {isGestao
            ? <button className="link-btn" onClick={desfazer} disabled={mut.isPending}>
                Desfazer vínculo
              </button>
            : <span className="muted">desfazer é ação da gestão (bv_users)</span>}
        </div>
      ) : !isGestao ? (
        <div className="muted">
          Sem vínculo. Criar vínculo é ação da <b>gestão</b> (grupo <code>bv_users</code>) —
          classificar como Substituído tira um EGP do escopo e põe outro.
        </div>
      ) : (
        <div className="vinc-form">
          <label>
            <span>Tipo</span>
            <select value={tipo} onChange={(e) => setTipo(e.target.value)}
              title="Como este EGP se liga ao sucessor. Não é derivável do arquivo — a gestão decide.">
              <option value="">— tipo —</option>
              {TIPOS_VINCULO.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <label className="vinc-suc">
            <span>Sucessor (projeto do corpus)</span>
            <input type="text" list={listId} value={sucessor} placeholder="Área__nome__ATU…"
              title="Chave do projeto no corpus — digite para buscar entre os EGPs existentes"
              onChange={(e) => setSucessor(e.target.value)} />
            <datalist id={listId}>
              {projetos.map((p) => <option key={p} value={p} />)}
            </datalist>
          </label>
          <button className="link-btn" disabled={!vinculoCompleto(tipo, sucessor) || mut.isPending}
            onClick={() => mut.mutate({ egp_vinculo_tipo: tipo.trim(), egp_sucessor: sucessor.trim() })}>
            {mut.isPending ? "vinculando…" : "Vincular"}
          </button>
          {tipo && <div className="muted vinc-ajuda">{TIPO_AJUDA[tipo]}</div>}
          {tipo === TIPO_SUBSTITUIDO && (
            <div className="muted vinc-ajuda">
              Fechar este EGP continua sendo um clique seu depois — classificar nunca muda
              status sozinho.
            </div>
          )}
          {sugestao && sucessor === sugestao && (
            <div className="muted vinc-ajuda">
              Sucessor sugerido pela versão já vinculada na comparação
              (<code>{row?.egp_atualizado_key}</code>) — confira e troque se não for.
            </div>
          )}
          {candidatos.length > 1 && (
            <div className="muted vinc-ajuda">
              {candidatos.length} versões de <code>{row?.egp_atualizado_key}</code> já estão no
              corpus ({candidatos.map(shortName).join(", ")}) — aponte qual delas sucede este
              EGP; o app não escolhe por você.
            </div>
          )}
        </div>
      )}

      {erro && <div className="error">Vínculo recusado: {erro}</div>}
      {nodesQ.error && <div className="error">Falha ao carregar os projetos do corpus: {String(nodesQ.error)}</div>}
    </div>
  );
}
